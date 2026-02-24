#!/usr/bin/env python3
# send_radarr_test.py
import json
import requests

URL = "http://127.0.0.1:8124/api/sonarr"  # adapte si besoin

payload = {
  "series": {
    "id": 78,
    "title": "Oshi no Ko",
    "titleSlug": "oshi-no-ko",
    "path": "/nas-omv/Animes/Oshi no Ko (2023) {tvdb-421069}",
    "tvdbId": 421069,
    "tvMazeId": 67635,
    "tmdbId": 203737,
    "imdbId": "tt21030032",
    "type": "anime",
    "year": 2023,
    "genres": [
      "Animation",
      "Anime",
      "Drama",
      "Mystery",
      "Romance"
    ],
    "images": [
      {
        "coverType": "banner",
        "url": "/MediaCover/78/banner.jpg?lastWrite=638869170007363215",
        "remoteUrl": "https://artworks.thetvdb.com/banners/v4/series/421069/banners/64545cec4d24d.jpg"
      },
      {
        "coverType": "poster",
        "url": "/MediaCover/78/poster.jpg?lastWrite=638869170007923242",
        "remoteUrl": "https://artworks.thetvdb.com/banners/v4/series/421069/posters/641e6afe38b06.jpg"
      },
      {
        "coverType": "fanart",
        "url": "/MediaCover/78/fanart.jpg?lastWrite=638869170008483270",
        "remoteUrl": "https://artworks.thetvdb.com/banners/v4/series/421069/backgrounds/6464dac0a7336.jpg"
      },
      {
        "coverType": "clearlogo",
        "url": "/MediaCover/78/clearlogo.png?lastWrite=638869170008843287",
        "remoteUrl": "https://artworks.thetvdb.com/banners/v4/series/421069/clearlogo/6440fff03273e.png"
      }
    ],
    "tags": [
      "animestorrent"
    ],
    "originalLanguage": {
      "id": 8,
      "name": "Japanese"
    }
  },
  "episodes": [
    {
      "id": 14255,
      "episodeNumber": 6,
      "seasonNumber": 3,
      "title": "TBA",
      "airDate": "2026-02-18",
      "airDateUtc": "2026-02-18T14:00:00Z",
      "seriesId": 78,
      "tvdbId": 11515138
    }
  ],
  "episodeFiles": [
    {
      "id": 15553,
      "relativePath": "Oshi no Ko (2023) - S03E06 - 030 - TBA [VOSTFR WEBDL-1080p].mkv",
      "path": "/nas-omv/Animes/Oshi no Ko (2023) {tvdb-421069}/Oshi no Ko (2023) - S03E06 - 030 - TBA [VOSTFR WEBDL-1080p].mkv",
      "quality": "WEBDL-1080p",
      "qualityVersion": 1,
      "releaseGroup": "Tsundere-Raws",
      "size": 590220602,
      "dateAdded": "2026-02-18T15:19:22.909501Z",
      "languages": [
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x264",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    }
  ],
  "downloadClient": "qBittorrent (animes)",
  "downloadClientType": "qBittorrent",
  "downloadId": "44E8D8J583B4FC5444F06FE230B79048F6P65229",
  "release": {
    "releaseTitle": "Oshi no Ko S03E06 VOSTFR 1080p WEB x264 AAC -Tsundere-Raws (ADN) ([Oshi no Ko] 3rd Season,[Oshi No Ko] Season 3)",
    "indexer": "Nyaa.si (Prowlarr)",
    "size": 590243456,
    "releaseType": "singleEpisode"
  },
  "fileCount": 1,
  "sourcePath": "/nas-omv/Downloads/Complet/animes/Oshi no Ko S03E06 VOSTFR 1080p WEB x264 AAC -Tsundere-Raws (ADN).mkv",
  "destinationPath": "/nas-omv/Animes/Oshi no Ko (2023) {tvdb-421069}",
  "eventType": "Download",
  "instanceName": "Sonarr",
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
