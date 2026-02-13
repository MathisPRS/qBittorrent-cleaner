#!/usr/bin/env python3
# send_radarr_test.py
import json
import requests

URL = "http://127.0.0.1:8129/api/radarr"  # adapte si besoin

payload = {
  "movie": {
    "id": 597,
    "title": "Taken 2",
    "year": 2012,
    "releaseDate": "2013-02-06",
    "folderPath": "/nas-omv/Films/Taken 2 (2012)",
    "tmdbId": 82675,
    "imdbId": "tt1397280",
    "overview": "In Istanbul, retired CIA operative Bryan Mills and his wife are taken hostage by the father of a kidnapper Mills killed while rescuing his daughter.",
    "genres": ["Action", "Crime", "Thriller"],
    "images": [
      {"coverType": "poster", "url": "/MediaCover/597/poster.jpg?lastWrite=639065794429856486", "remoteUrl": "https://image.tmdb.org/t/p/original/yzAlcuJhpnxRPjaj7AHBRbNPQCJ.jpg"},
      {"coverType": "fanart", "url": "/MediaCover/597/fanart.jpg?lastWrite=639065794430576461", "remoteUrl": "https://image.tmdb.org/t/p/original/5M92Rtz6r01HLrN0TMrU8jCbyVm.jpg"}
    ],
    "tags": ["filmstorrent"],
    "originalLanguage": {"id": 1, "name": "English"}
  },
  "remoteMovie": {
    "tmdbId": 82675,
    "imdbId": "tt1397280",
    "title": "Taken 2",
    "year": 2012
  },
  "movieFile": {
    "id": 753,
    "relativePath": "Taken 2 (2012) 82675.mkv",
    "path": "/nas-omv/Films/Taken 2 (2012)/Taken 2 (2012) 82675.mkv",
    "quality": "Bluray-1080p",
    "qualityVersion": 1,
    "releaseGroup": "MM91",
    "sceneName": "Taken 2 (2012) Version Non Censurée MULTi VFF 1080p 10bit HDLight BluRay x265 AC3 5.1-MM91",
    "indexerFlags": "0",
    "size": 2634071875,
    "dateAdded": "2026-02-13T11:40:00.0875003Z",
    "languages": [{"id": 2, "name": "French"}, {"id": 1, "name": "English"}],
    "mediaInfo": {
      "audioChannels": 5.1,
      "audioCodec": "AC3",
      "audioLanguages": ["fre", "eng"],
      "height": 800,
      "width": 1920,
      "subtitles": ["fre"],
      "videoCodec": "x265",
      "videoDynamicRange": "",
      "videoDynamicRangeType": ""
    },
    "sourcePath": "/nas-omv/Downloads/Complet/films/Taken 2 (2012) Version Non Censurée MULTi VFF 1080p 10bit HDLight BluRay x265 AC3 5.1-MM91.mkv"
  },
  "isUpgrade": False,
  "downloadClient": "qBittorrent (films)",
  "downloadClientType": "qBittorrent",
  "downloadId": "6D667BB7F1DDE5A7554D66637177D652591C2F32",
  "customFormatInfo": {
    "customFormats": [
      {"id": 13, "name": "1080p"},
      {"id": 39, "name": "Entre 0GB et 15 GB"},
      {"id": 11, "name": "Language: Original + French"},
      {"id": 12, "name": "MULTi"},
      {"id": 32, "name": "x265"}
    ],
    "customFormatScore": 5500
  },
  "release": {
    "releaseTitle": "Taken 2 (2012) Version Non Censurée MULTi VFF 1080p 10bit HDLight BluRay x265 AC3 5.1-MM91",
    "indexer": "Ygégé (Prowlarr)",
    "size": 2630667520,
    "indexerFlags": []
  },
  "eventType": "Download",
  "instanceName": "Radarr",
  "applicationUrl": ""
}

headers = {"Content-Type": "application/json"}

print("Sending POST to", URL)
resp = requests.post(URL, headers=headers, data=json.dumps(payload), timeout=10)

print("Status:", resp.status_code)
try:
    print("Response JSON:", resp.json())
except Exception:
    print("Response text:", resp.text)
