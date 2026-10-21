# -*- coding: utf-8 -*-
"""
build_apple_sessions.py

애플 뮤직 원본 재생 로그(Apple Music Play Activity.csv)에서 "실제로 들은
재생 기록"만 뽑아 last.fm 스크로블과 같은 형식(uts,utc_time,artist,album,track)
으로 변환하는 스크립트.

배경 (이 스크립트가 고치는 버그)
--------------------------------
애플 뮤직의 재생 로그(Play Activity.csv)에는 한 번의 실제 재생에 대해
서로 다른 Event Type의 행이 여러 개 같이 찍힌다.

  - PLAY_START  : 재생을 시작했다는 이벤트. Play Duration Milliseconds가
                   대부분 비어 있어(=재생시간 정보 없음) 단독으로는 쓸 수 없음.
  - PLAY_END    : 재생이 끝나거나 중단됐을 때 찍히는 이벤트. 실제 재생시간
                   (Play Duration Milliseconds)과 재생 구간(Start/End Position
                   In Milliseconds)이 정확히 들어있는, "진짜" 재생 기록.
  - LYRIC_DISPLAY: 가사 표시 UI가 떠 있던 구간을 추적하는 이벤트. 그런데
                   이 이벤트도 PLAY_END와 거의 동일한 Play Duration
                   Milliseconds / Media Duration In Milliseconds 값을
                   독립적으로 가지고 있다.

예전 버전 스크립트(rebuild_music.py)는 Event Type을 구분하지 않고 모든 행에
"재생시간이 곡 길이의 50% 이상 또는 240초 이상이면 재생으로 인정" 규칙을
그대로 적용했다. 그 결과 PLAY_END 행 하나로 이미 인정된 "진짜 재생 1회"가,
같은 재생에 대한 LYRIC_DISPLAY 행에서 또 한 번 규칙을 통과해 "가짜로 하나
더" 만들어졌다. 이게 last.fm 데이터의 A(애플 유래) 쪽에서 발견된 "같은
곡이 몇 초/몇 분 간격으로 여러 번 찍히는" 오류의 실제 원인이었다
(2025-06-22 Radiohead Kid A 앨범 청취 기록에서 최초 발견).

또한 같은 실제 청취가 여러 개의 PLAY_END "체크포인트" 행으로 나뉘어
기록되는 경우도 있다(예: 곡을 듣다가 백그라운드로 전환 등). 이런 조각들은
재생 구간이 서로 이어져 있다(앞 조각이 끝난 위치 ≈ 다음 조각이 시작한
위치) — 이런 경우는 하나의 세션으로 합쳐서 재생시간을 합산해야 한다.

알고리즘
-------
1. Event Type == 'PLAY_END' 인 행뫌 사용한다 (PLAY_START, LYRIC_DISPLAY 제외).
2. (곡명, 앨범명) 별로 모은 뒤 시간순 정밬.
3. 인접한 뱐 조각을 두 즰보 인념 모두 만걱하면 같은 세션으로 병합:
     - 위치 연속성: |다음 조각 시작위치 - 이전 조각 끝위치| <= POS_TOL(ms)
     - 시간 인접성: 0 <= (다음 조각 시작시각 - 이전 조각 끝시각) <= TIME_GAP_TOL(초)
4. 세션 단위로 재생시간을 합산해 50%/240초 규칙 적용.
5. 아티스트/앨범은 기존과 동일한 계층적 조인으로 보강한다:
     Container Details.csv(앨범명->아티스트) ->
     Library Tracks.json.zip / 플레이리스트.xml / 전체.xml((곡명,앨범명)->아티스트,
     곡명이 라이브러리 전체에서 유일하면 곡명만으로도 매칭)

사용법
------
    python3 build_apple_sessions.py \
        --apple-activity "Apple Music Play Activity.csv" \
        --library-json "Apple Music Library Tracks.json.zip" \
        --container-details "Apple Music - Container Details.csv" \
        --playlist-xml "플레이리스트.xml" \
        --full-xml "전체.xml" \
        --output "Apple Music Play Activity (edited).csv"

원본 Apple Music Play Activity.csv는 읽기만 하고 절대 수정하지 않는다.
출력 파일은 임시 파일에 먼저 쓴 뒤 os.replace로 원자적으로 교체한다.
"""

import argparse
import csv
import json
import os
import plistlib
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

POS_TOL_MS = 3000     # 위치 연속성 허용 오차 (ms)
TIME_GAP_TOL_SEC = 1800  # 세션으로 묶을 최대 시간 간격 (초)


def parse_ts(s):
    if not s:
        return None
    s = s.strip()
    try:
        if '.' in s:
            dt = datetime.strptime(s[:23], '%Y-%m-%dT%H:%M:%S.%f')
        else:
            dt = datetime.strptime(s[:19], '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


def to_num(s):
    s = (s or '').strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_artist_lookup(container_details_path, library_json_path, playlist_xml_path, full_xml_path):
    """(곡명, 앨범명) -> 아티스트 조회 테이블들을 구성한다."""
    album_artist = {}
    if container_details_path and os.path.exists(container_details_path):
        with open(container_details_path, 'r', encoding='utf-8', errors='replace', newline='') as fh:
            reader = csv.reader(fh)
            header = next(reader)
            idx = {h: i for i, h in enumerate(header)}
            for r in reader:
                if r[idx['Container Type']] != 'ALBUM':
                    continue
                desc = r[idx['Container Description']]
                artists = r[idx['Artists']]
                if artists in ('N/A', ''):
                    continue
                prefix = artists + ' - '
                title = desc[len(prefix):] if desc.startswith(prefix) else desc
                album_artist.setdefault(title, artists)

    by_title = defaultdict(set)
    title_album_artist = {}

    def ingest(title, artist, album):
        title = (title or '').strip()
        artist = (artist or '').strip()
        album = (album or '').strip()
        if not title or not artist:
            return
        if album:
            title_album_artist.setdefault((title, album), artist)
        by_title[title].add((artist, album))

    if library_json_path and os.path.exists(library_json_path):
        with zipfile.ZipFile(library_json_path) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                for t in json.load(f):
                    ingest(t.get('Title'), t.get('Artist'), t.get('Album'))

    for xml_path in (playlist_xml_path, full_xml_path):
        if xml_path and os.path.exists(xml_path):
            with open(xml_path, 'rb') as f:
                for t in plistlib.load(f)['Tracks'].values():
                    ingest(t.get('Name'), t.get('Artist'), t.get('Album'))

    unique_title_artist_album = {t: next(iter(v)) for t, v in by_title.items() if len(v) == 1}

    def lookup(track, album):
        a = title_album_artist.get((track, album)) if album else None
        if a:
            return a, album
        if album:
            a2 = album_artist.get(album)
            if a2:
                return a2, album
        combo = unique_title_artist_album.get(track)
        if combo:
            return combo[0], (album or combo[1])
        return '', album

    return lookup


def load_play_end_segments(apple_activity_path):
    """PLAY_END 행만 (곡명, 앨범명) 별로 모아서 반환한다."""
    groups = defaultdict(list)
    stats = {'total_play_end': 0, 'skipped_no_track': 0, 'skipped_no_ts': 0, 'skipped_no_play_ms': 0}

    with open(apple_activity_path, 'r', encoding='utf-8', errors='replace', newline='') as fin:
        reader = csv.reader(fin)
        header = next(reader)
        idx = {h: i for i, h in enumerate(header)}
        for r in reader:
            if r[idx['Event Type']] != 'PLAY_END':
                continue
            stats['total_play_end'] += 1
            track = r[idx['Song Name']].strip()
            if not track:
                stats['skipped_no_track'] += 1
                continue
            st = parse_ts(r[idx['Event Start Timestamp']])
            et = parse_ts(r[idx['Event End Timestamp']]) or st
            if st is None:
                stats['skipped_no_ts'] += 1
                continue
            play_ms = to_num(r[idx['Play Duration Milliseconds']])
            if play_ms is None:
                stats['skipped_no_play_ms'] += 1
                continue
            media_ms = to_num(r[idx['Media Duration In Milliseconds']]) or 0
            startpos = to_num(r[idx['Start Position In Milliseconds']]) or 0
            endpos = to_num(r[idx['End Position In Milliseconds']]) or 0
            album = r[idx['Album Name']].strip() or r[idx['Container Album Name']].strip()
            groups[(track, album)].append({
                'st': st, 'et': et, 'play_ms': play_ms, 'media_ms': media_ms,
                'startpos': startpos, 'endpos': endpos,
            })
    return groups, stats


def build_sessions(segs):
    """위치가 이어지는 조각들을 하나의 실제 청취 세션으로 병합한다."""
    segs = sorted(segs, key=lambda s: s['st'])
    sessions = []
    cur = [segs[0]]
    for prev, seg in zip(segs, segs[1:]):
        pos_gap = abs(seg['startpos'] - prev['endpos'])
        time_gap = (seg['st'] - prev['et']).total_seconds()
        if pos_gap <= POS_TOL_MS and 0 <= time_gap <= TIME_GAP_TOL_SEC:
            cur.append(seg)
        else:
            sessions.append(cur)
            cur = [seg]
    sessions.append(cur)
    return sessions


def qualifies(total_play_ms, media_ms):
    if media_ms <= 0:
        return False
    return total_play_ms >= 240000 or total_play_ms >= 0.5 * media_ms


def build_rows(groups, lookup_artist):
    total_sessions = 0
    multi_seg_count = 0
    matched_artist = 0
    rows = []

    for (track, album), segs in groups.items():
        sessions = build_sessions(segs)
        total_sessions += len(sessions)
        for sess in sessions:
            total_play_ms = sum(s['play_ms'] for s in sess)
            media_ms = max(s['media_ms'] for s in sess)
            if not qualifies(total_play_ms, media_ms):
                continue
            if len(sess) > 1:
                multi_seg_count += 1
            uts = int(sess[0]['st'].timestamp())
            utc_time = sess[0]['st'].strftime('%Y-%m-%d %H:%M')
            artist, out_album = lookup_artist(track, album)
            if artist:
                matched_artist += 1
            rows.append((uts, utc_time, artist, out_album, track))

    rows.sort(key=lambda x: -x[0])
    return rows, {
        'total_sessions': total_sessions,
        'qualifying': len(rows),
        'multi_seg': multi_seg_count,
        'matched_artist': matched_artist,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apple-activity', required=True, help='Apple Music Play Activity.csv (원본, 읽기 전용)')
    ap.add_argument('--library-json', help='Apple Music Library Tracks.json.zip')
    ap.add_argument('--container-details', help='Apple Music - Container Details.csv')
    ap.add_argument('--playlist-xml', help='플레이리스트.xml')
    ap.add_argument('--full-xml', help='전체.xml (라이브러리 전체)')
    ap.add_argument('--output', required=True, help='출력 CSV 경로 (uts,utc_time,artist,album,track)')
    args = ap.parse_args()

    lookup_artist = load_artist_lookup(
        args.container_details, args.library_json, args.playlist_xml, args.full_xml
    )

    groups, stats = load_play_end_segments(args.apple_activity)
    print('원본 PLAY_END 행 수:', stats['total_play_end'])
    print('  - 곡명 없음 제외:', stats['skipped_no_track'])
    print('  - 시작시각 파싱 실패 제외:', stats['skipped_no_ts'])
    print('  - 재생시간 데이터 없음 제외:', stats['skipped_no_play_ms'])

    rows, build_stats = build_rows(groups, lookup_artist)

    tmp_path = args.output + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8', newline='') as fout:
        writer = csv.writer(fout)
        writer.writerow(['uts', 'utc_time', 'artist', 'album', 'track'])
        for row in rows:
            writer.writerow(row)
    os.replace(tmp_path, args.output)

    print()
    print('병합된 세션 총 개수:', build_stats['total_sessions'])
    print('조건(50%/240s) 만족 세션(=최종 재생 기록) 수:', build_stats['qualifying'])
    print('  - 그 중 여러 PLAY_END 조각이 하나로 병합된 세션:', build_stats['multi_seg'])
    if build_stats['qualifying']:
        pct = build_stats['matched_artist'] / build_stats['qualifying'] * 100
        print(f"아티스트 매칭: {build_stats['matched_artist']}/{build_stats['qualifying']} = {pct:.1f}%")
    print()
    print('=> 저장 완료:', args.output)


if __name__ == '__main__':
    main()
