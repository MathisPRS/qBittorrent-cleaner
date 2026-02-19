#!/usr/bin/env python3
# send_radarr_test.py
import json
import requests

URL = "http://127.0.0.1:8124/api/sonarr"  # adapte si besoin

payload = {
  "series": {
    "id": 666,
    "title": "TEST",
    "titleSlug": "gachiakuta",
    "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}",
    "tvdbId": 450537,
    "tvMazeId": 81834,
    "tmdbId": 256721,
    "imdbId": "tt32612521",
    "type": "anime",
    "year": 2025,
    "genres": [
      "Action",
      "Anime",
      "Fantasy"
    ],
    "images": [
      {
        "coverType": "banner",
        "url": "/MediaCover/86/banner.jpg?lastWrite=638876138428255258",
        "remoteUrl": "https://artworks.thetvdb.com/banners/v4/series/450537/banners/6867cf226c9c2.jpg"
      },
      {
        "coverType": "poster",
        "url": "/MediaCover/86/poster.jpg?lastWrite=638876138434814998",
        "remoteUrl": "https://artworks.thetvdb.com/banners/v4/series/450537/posters/678f825546924.jpg"
      },
      {
        "coverType": "fanart",
        "url": "/MediaCover/86/fanart.jpg?lastWrite=638876138439294820",
        "remoteUrl": "https://artworks.thetvdb.com/banners/v4/series/450537/backgrounds/686b2576e31b6.jpg"
      },
      {
        "coverType": "clearlogo",
        "url": "/MediaCover/86/clearlogo.png?lastWrite=639062877710755973",
        "remoteUrl": "https://artworks.thetvdb.com/banners/v4/series/450537/clearlogo/686b15719a454.png"
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
      "id": 5988,
      "episodeNumber": 1,
      "seasonNumber": 1,
      "title": "The Sphere",
      "overview": "Bullied outcast Rudo finds respite in repurposing trash, until a terrible tragedy changes his life forever.",
      "airDate": "2025-07-06",
      "airDateUtc": "2025-07-06T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 10541264
    },
    {
      "id": 5989,
      "episodeNumber": 2,
      "seasonNumber": 1,
      "title": "The Inhabited",
      "overview": "Cast into the Pit, Rudo is saved by the mysterious Enjin who may not have his best interests at heart.",
      "airDate": "2025-07-13",
      "airDateUtc": "2025-07-13T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180307
    },
    {
      "id": 5990,
      "episodeNumber": 3,
      "seasonNumber": 1,
      "title": "The Ground",
      "overview": "Enjin teaches Rudo about life on the Ground, but an encounter with a churlish stranger may cut his time short.",
      "airDate": "2025-07-27",
      "airDateUtc": "2025-07-27T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180308
    },
    {
      "id": 5991,
      "episodeNumber": 4,
      "seasonNumber": 1,
      "title": "Cleaner HQ",
      "overview": "After being introduced to Cleaner HQ, Rudo follows Riyo on a job to learn the business.",
      "airDate": "2025-08-03",
      "airDateUtc": "2025-08-03T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180309
    },
    {
      "id": 5992,
      "episodeNumber": 5,
      "seasonNumber": 1,
      "title": "Raiders",
      "overview": "The Cleaners go on a job to save another Sphereite who survived the fall. Rudo tags along to learn more.",
      "airDate": "2025-08-10",
      "airDateUtc": "2025-08-10T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180310
    },
    {
      "id": 5993,
      "episodeNumber": 6,
      "seasonNumber": 1,
      "title": "One Good Strike!!",
      "overview": "With the job having gone terribly wrong, Rudo finds himself face to face with a merciless Raider named Jabber.",
      "airDate": "2025-08-17",
      "airDateUtc": "2025-08-17T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180311
    },
    {
      "id": 5994,
      "episodeNumber": 7,
      "seasonNumber": 1,
      "title": "A Score to Settle",
      "overview": "Jabber employs a new strategy to get through Rudo's defenses, and another ally joins the fray.",
      "airDate": "2025-08-24",
      "airDateUtc": "2025-08-24T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180312
    },
    {
      "id": 5995,
      "episodeNumber": 8,
      "seasonNumber": 1,
      "title": "Moving Forward",
      "overview": "Rudo deals with the emotional aftermath of the Jabber fight and gets a new lead about returning to the Sphere.",
      "airDate": "2025-08-31",
      "airDateUtc": "2025-08-31T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180313
    },
    {
      "id": 5996,
      "episodeNumber": 9,
      "seasonNumber": 1,
      "title": "The City of Graffiti",
      "overview": "To get a \"spell\" for their next mission, the Cleaners head to Canvas Town, where they make a tragic discovery.",
      "airDate": "2025-09-07",
      "airDateUtc": "2025-09-07T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180314
    },
    {
      "id": 5997,
      "episodeNumber": 10,
      "seasonNumber": 1,
      "title": "Penta: The Desert No Man's Land",
      "overview": "With their gear-up complete, the crew heads into the No Man's Land, Penta, to get clues about the Sphere.",
      "airDate": "2025-09-14",
      "airDateUtc": "2025-09-14T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180315
    },
    {
      "id": 5998,
      "episodeNumber": 11,
      "seasonNumber": 1,
      "title": "Amo's Hospitality",
      "overview": "A mysterious woman living in the No Man's Land challenges the crew from an unexpected angle.",
      "airDate": "2025-09-21",
      "airDateUtc": "2025-09-21T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180316
    },
    {
      "id": 5999,
      "episodeNumber": 12,
      "seasonNumber": 1,
      "title": "Something Like a Curse",
      "overview": "Tamsy and Zanka fight to save their captive allies. In the aftermath, Rudo has an unexpected reaction.",
      "airDate": "2025-09-28",
      "airDateUtc": "2025-09-28T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11180317
    },
    {
      "id": 6000,
      "episodeNumber": 13,
      "seasonNumber": 1,
      "title": "An Empty Gaze",
      "overview": "Amo tells the story of how she came to the tower and of the \"angels\" who came to visit her.",
      "airDate": "2025-10-05",
      "airDateUtc": "2025-10-05T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221450
    },
    {
      "id": 6001,
      "episodeNumber": 14,
      "seasonNumber": 1,
      "title": "The Storm Before the Storm",
      "overview": "After returning from the Penta No Man's Land, Rudo and the Cleaners face a series of new threats.",
      "airDate": "2025-10-12",
      "airDateUtc": "2025-10-12T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221451
    },
    {
      "id": 6002,
      "episodeNumber": 15,
      "seasonNumber": 1,
      "title": "Clash!",
      "overview": "Taken by the Raiders to an unknown setting, the Cleaners fight for their lives, and Zodyl makes Rudo an offer.",
      "airDate": "2025-10-19",
      "airDateUtc": "2025-10-19T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221453
    },
    {
      "id": 6003,
      "episodeNumber": 16,
      "seasonNumber": 1,
      "title": "Gifted and Not",
      "overview": "Bundus interrogates the Santas while Zanka struggles to keep pace with a powered-up Jabber.",
      "airDate": "2025-10-26",
      "airDateUtc": "2025-10-26T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221454
    },
    {
      "id": 6004,
      "episodeNumber": 17,
      "seasonNumber": 1,
      "title": "Memories of a Mediocrity",
      "overview": "Zanka reflects on the turning point in his past that brought him to where he is today.",
      "airDate": "2025-11-02",
      "airDateUtc": "2025-11-02T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221455
    },
    {
      "id": 6005,
      "episodeNumber": 18,
      "seasonNumber": 1,
      "title": "Oh Zap, Totes Legit",
      "overview": "While the Raiders-Cleaners conflicts continue, the battle between Riyo and Noerde heats up.",
      "airDate": "2025-11-09",
      "airDateUtc": "2025-11-09T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221456
    },
    {
      "id": 6006,
      "episodeNumber": 19,
      "seasonNumber": 1,
      "title": "Watchman Series",
      "overview": "Zodyl reveals his plan to reach the Sphere, and the other Cleaners react to their current circumstances.",
      "airDate": "2025-11-16",
      "airDateUtc": "2025-11-16T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221457
    },
    {
      "id": 6007,
      "episodeNumber": 20,
      "seasonNumber": 1,
      "title": "Ensign",
      "overview": "As the battle climaxes, Enjin makes a play to unite his team, and Zodyl makes his final entreaty to Rudo.",
      "airDate": "2025-11-23",
      "airDateUtc": "2025-11-23T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221458
    },
    {
      "id": 6008,
      "episodeNumber": 21,
      "seasonNumber": 1,
      "title": "TIME ATTACK",
      "overview": "The Cleaners attempt to stop their \"runaway train,\" but Bundus stands in the way.",
      "airDate": "2025-11-30",
      "airDateUtc": "2025-11-30T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221459
    },
    {
      "id": 6009,
      "episodeNumber": 22,
      "seasonNumber": 1,
      "title": "The Power of Protection",
      "overview": "An unexpected member of the Raiders returns in a last-ditch effort to keep the Cleaners locked down.",
      "airDate": "2025-12-07",
      "airDateUtc": "2025-12-07T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221460
    },
    {
      "id": 6010,
      "episodeNumber": 23,
      "seasonNumber": 1,
      "title": "The Man Who Will Be Stronger",
      "overview": "As the Cleaners take stock after the battle, a convalescing Zanka receives some surprising news.",
      "airDate": "2025-12-14",
      "airDateUtc": "2025-12-14T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221461
    },
    {
      "id": 6011,
      "episodeNumber": 24,
      "seasonNumber": 1,
      "title": "Field Trip",
      "overview": "Rudo and the other child Cleaners take a trip to Canvas Town while Corvus entertains some unwanted guests.",
      "airDate": "2025-12-21",
      "airDateUtc": "2025-12-21T14:30:00Z",
      "seriesId": 86,
      "tvdbId": 11221462
    }
  ],
  "episodeFiles": [
    {
      "id": 15560,
      "relativePath": "Gachiakuta (2025) - S01E01 - 001 - The Sphere [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E01 - 001 - The Sphere [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E01.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 390477937,
      "dateAdded": "2026-02-18T15:40:44.4763371Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15561,
      "relativePath": "Gachiakuta (2025) - S01E02 - 002 - The Inhabited [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E02 - 002 - The Inhabited [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E02.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 440424807,
      "dateAdded": "2026-02-18T15:40:44.522674Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15562,
      "relativePath": "Gachiakuta (2025) - S01E03 - 003 - The Ground [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E03 - 003 - The Ground [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E03.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 362230622,
      "dateAdded": "2026-02-18T15:40:44.5597464Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15563,
      "relativePath": "Gachiakuta (2025) - S01E04 - 004 - Cleaner HQ [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E04 - 004 - Cleaner HQ [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E04.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 406731704,
      "dateAdded": "2026-02-18T15:40:44.6004877Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15564,
      "relativePath": "Gachiakuta (2025) - S01E05 - 005 - Raiders [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E05 - 005 - Raiders [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E05.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 398518481,
      "dateAdded": "2026-02-18T15:40:44.642848Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15565,
      "relativePath": "Gachiakuta (2025) - S01E06 - 006 - One Good Strike!! [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E06 - 006 - One Good Strike!! [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E06.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 396696947,
      "dateAdded": "2026-02-18T15:40:44.6883539Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15566,
      "relativePath": "Gachiakuta (2025) - S01E07 - 007 - A Score to Settle [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E07 - 007 - A Score to Settle [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E07.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 438356771,
      "dateAdded": "2026-02-18T15:40:44.738518Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15567,
      "relativePath": "Gachiakuta (2025) - S01E08 - 008 - Moving Forward [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E08 - 008 - Moving Forward [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E08.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 381967806,
      "dateAdded": "2026-02-18T15:40:44.778374Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15568,
      "relativePath": "Gachiakuta (2025) - S01E09 - 009 - The City of Graffiti [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E09 - 009 - The City of Graffiti [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E09.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 422189764,
      "dateAdded": "2026-02-18T15:40:44.8248344Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15569,
      "relativePath": "Gachiakuta (2025) - S01E10 - 010 - Penta The Desert No Mans Land [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E10 - 010 - Penta The Desert No Mans Land [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E10.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 459690253,
      "dateAdded": "2026-02-18T15:40:44.8694383Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15570,
      "relativePath": "Gachiakuta (2025) - S01E11 - 011 - Amos Hospitality [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E11 - 011 - Amos Hospitality [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E11.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 408192143,
      "dateAdded": "2026-02-18T15:40:44.9070255Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15571,
      "relativePath": "Gachiakuta (2025) - S01E12 - 012 - Something Like a Curse [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E12 - 012 - Something Like a Curse [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E12.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 399570761,
      "dateAdded": "2026-02-18T15:40:44.9737312Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15572,
      "relativePath": "Gachiakuta (2025) - S01E13 - 013 - An Empty Gaze [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E13 - 013 - An Empty Gaze [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E13.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 418142082,
      "dateAdded": "2026-02-18T15:40:45.0170801Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15573,
      "relativePath": "Gachiakuta (2025) - S01E14 - 014 - The Storm Before the Storm [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E14 - 014 - The Storm Before the Storm [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E14.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 375228695,
      "dateAdded": "2026-02-18T15:40:45.0579945Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15574,
      "relativePath": "Gachiakuta (2025) - S01E15 - 015 - Clash! [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E15 - 015 - Clash! [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E15.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 366832461,
      "dateAdded": "2026-02-18T15:40:45.1527951Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15575,
      "relativePath": "Gachiakuta (2025) - S01E16 - 016 - Gifted and Not [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E16 - 016 - Gifted and Not [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E16.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 378529195,
      "dateAdded": "2026-02-18T15:40:45.2234106Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15576,
      "relativePath": "Gachiakuta (2025) - S01E17 - 017 - Memories of a Mediocrity [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E17 - 017 - Memories of a Mediocrity [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E17.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 341913821,
      "dateAdded": "2026-02-18T15:40:45.2923369Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15577,
      "relativePath": "Gachiakuta (2025) - S01E18 - 018 - Oh Zap Totes Legit [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E18 - 018 - Oh Zap Totes Legit [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E18.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 380689211,
      "dateAdded": "2026-02-18T15:40:45.3641891Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15578,
      "relativePath": "Gachiakuta (2025) - S01E19 - 019 - Watchman Series [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E19 - 019 - Watchman Series [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E19.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 335874433,
      "dateAdded": "2026-02-18T15:40:45.5044999Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15579,
      "relativePath": "Gachiakuta (2025) - S01E20 - 020 - Ensign [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E20 - 020 - Ensign [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E20.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 328921630,
      "dateAdded": "2026-02-18T15:40:45.5593509Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15580,
      "relativePath": "Gachiakuta (2025) - S01E21 - 021 - TIME ATTACK [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E21 - 021 - TIME ATTACK [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E21.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 357739271,
      "dateAdded": "2026-02-18T15:40:45.7334644Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15581,
      "relativePath": "Gachiakuta (2025) - S01E22 - 022 - The Power of Protection [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E22 - 022 - The Power of Protection [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E22.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 434637493,
      "dateAdded": "2026-02-18T15:40:45.7935063Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15582,
      "relativePath": "Gachiakuta (2025) - S01E23 - 023 - The Man Who Will Be Stronger [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E23 - 023 - The Man Who Will Be Stronger [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E23.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 328052295,
      "dateAdded": "2026-02-18T15:40:45.9208373Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    },
    {
      "id": 15583,
      "relativePath": "Gachiakuta (2025) - S01E24 - 024 - Field Trip [MULTi WEBRip-1080p].mkv",
      "path": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}/Gachiakuta (2025) - S01E24 - 024 - Field Trip [MULTi WEBRip-1080p].mkv",
      "quality": "WEBRip-1080p",
      "qualityVersion": 1,
      "releaseGroup": "T3KASHi",
      "sceneName": "Gachiakuta.S01E24.FiNAL.MULTi.1080p.WEBRiP.x265-T3KASHi",
      "size": 329192227,
      "dateAdded": "2026-02-18T15:40:46.2904471Z",
      "languages": [
        {
          "id": 2,
          "name": "French"
        },
        {
          "id": 8,
          "name": "Japanese"
        }
      ],
      "mediaInfo": {
        "audioChannels": 2.0,
        "audioCodec": "AAC",
        "audioLanguages": [
          "fre",
          "jpn"
        ],
        "height": 1080,
        "width": 1920,
        "subtitles": [
          "fre"
        ],
        "videoCodec": "x265",
        "videoDynamicRange": "",
        "videoDynamicRangeType": ""
      }
    }
  ],
  "downloadClient": "qBittorrent (animes)",
  "downloadClientType": "qBittorrent",
  "downloadId": "66FEDFBF91230C53394C45B7A78B5AE052DB62E3",
  "release": {
    "releaseType": "seasonPack"
  },
  "fileCount": 24,
  "sourcePath": "/nas-omv/Downloads/Complet/animes/Gachiakuta.S01.MULTi.1080p.WEBRiP.x265-T3KASHi",
  "destinationPath": "/nas-omv/Animes/Gachiakuta (2025) {tvdb-450537}",
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
