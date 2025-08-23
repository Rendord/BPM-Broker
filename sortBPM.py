import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException
import time
import json
import requests
import urllib.parse
import re
import os

# Set up authentication
SPOTIPY_CLIENT_ID = os.getenv('spotify_client_id')
SPOTIPY_CLIENT_SECRET = os.getenv('')
SPOTIPY_REDIRECT_URI = "http://127.0.0.1:3000"

MUSICBRAINZ_ENDPOINT = "https://musicbrainz.org/ws/2/recording/"
ACOUSTICBRAINZ_ENDPOINT = "https://acousticbrainz.org/api/v1/"

# Define the scopes needed #TODO bring back scopes to what is purely necessary
SCOPE = "user-library-read playlist-modify-public playlist-modify-private playlist-read-collaborative playlist-read-private user-read-email user-read-private user-read-playback-state user-read-currently-playing"

# Initialize Spotipy
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID,
                                               client_secret=SPOTIPY_CLIENT_SECRET,
                                               redirect_uri=SPOTIPY_REDIRECT_URI,
                                               scope=SCOPE))

# Get user ID
user_id = sp.me()["id"]

non_bpm_playlists = [] # list of ID's 

bpm_playlists = {} # key BPM -> ID playlist

track_dictionary = {} # playlist ID -> list of track ID's
 
#playlist_tracks


def is_valid_track(sp, track_id):
    try:
        track = sp.track(track_id)  # Try to fetch the track details
        return True  # Track is valid if we can retrieve it
    except SpotifyException as e:
        if e.http_status == 404:
            print(f"Track {track_id} does not exist (404).")
        elif e.http_status == 403:
            print(f"Track {track_id} is region-locked or unavailable (403).")
        else:
            print(f"Error fetching track {track_id}: {e}")
        return False  # If the track couldn't be retrieved, it's invalid

def handle_spotify_exception(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except SpotifyException as e:
        if e.http_status == 429:
            print("Rate limit exceeded. Sleeping for 30 seconds...")
            time.sleep(30)
            return handle_spotify_exception(func, *args, **kwargs)  # Retry the call
        elif e.http_status == 403:
            print("403 Forbidden: Track is unavailable (possibly region-locked). Skipping...")
            return None
        else:
            raise e

#handles requesting to rate limited API's limit = seconds per request, default = 1.5 for musicbrainz
def handle_rate_limited_request(url, sleep_time=1.5, max_retries=10):
    retries = 0

    headers = {
        "User-Agent": "BPM-Broker/1.0 (rendord@gmail.com)",
        "Accept": "application/json"
    }
    

    while retries < max_retries:
        response = requests.get(url,headers=headers)

        if response.status_code == 200:
            return response.json()
        elif response.status_code in [429,503,403]:
            print(f"Rate limit hit ({response.status_code}). Retrying in {sleep_time} seconds...")
            time.sleep(sleep_time) #little offset to make sure we aren't bumping the limit
            retries += 1
        else:
            print(f"Request failed with status {response.status_code}: {response.text}")
            return None
        
    print("Max retries reached")
#query=recording:Creep AND artist:Radiohead AND release:Pablo Honey AND NOT comment:live&limit=1&fmt=json
def build_query(title, artist, album=None):
    query_parts = [f"recording:{title}", f"artist:{artist}", "NOT comment:live"]
    if album:
        query_parts.insert(2, f"release:{album}")
    query_string = " AND ".join(query_parts)
    return urllib.parse.quote(query_string)

def fetch_musicbrainz_data(query):
    url = f"{MUSICBRAINZ_ENDPOINT}?query={query}&limit=1&fmt=json"
    return handle_rate_limited_request(url)

def fetch_acousticbrainz_data(mbid):
    url = f"{ACOUSTICBRAINZ_ENDPOINT}{mbid}/low-level"
    return handle_rate_limited_request(url)

def get_x_liked_songs(amount, max=50):
    if amount > max:
        amount = 50
    songs = []
    results = handle_spotify_exception(sp.current_user_saved_tracks, limit=amount)
    for item in results["items"]:
            track = item["track"]
            songs.append((track["id"], track["name"]))
    return songs

def get_liked_songs():
    songs = []
    results = handle_spotify_exception(sp.current_user_saved_tracks, limit=50)
    while results:
        for item in results["items"]:
            track = item["track"]
            #print(json.dumps(track, indent=4))
            songs.append((track["id"], track["name"]))
        results = handle_spotify_exception(sp.next, results) if results["next"] else None
    return songs

def get_track_bpm(track_id):

    #print(json.dumps(sp.track(track_id), indent=4))

    track = sp.track(track_id)
    title = track["name"]
    artist = track["artists"][0]["name"]
    album = track["album"]["name"]


    query_string = build_query(title, artist, album)
    musicbrainz_data = fetch_musicbrainz_data(query_string)

    if not musicbrainz_data or not musicbrainz_data.get("recordings"):
        #fallback search
        query_string = build_query(title,artist)
        musicbrainz_data = fetch_musicbrainz_data(query_string)
        
    if not musicbrainz_data or not musicbrainz_data.get("recordings"):
        print("No MusicBrainz match found.")
        return 0
    
    try:
        mbid = musicbrainz_data["recordings"][0]["id"]
        acousticbrainz_data = fetch_acousticbrainz_data(mbid)
        print(mbid)
        bpm = round(acousticbrainz_data["rhythm"]["bpm"]) if acousticbrainz_data else 0
    except IndexError:
        print("Oops! That index doesn't exist.")
        bpm = 0

    return bpm

def get_or_create_playlist(name, bpm):
    if bpm in bpm_playlists.keys():
        return bpm_playlists.get(bpm)
    else:
        playlist = sp.user_playlist_create(user=user_id, name=name, public=False)
        bpm_playlists[bpm] = playlist["id"]
        return playlist["id"]
    
def retrieve_playlists():
    user_playlists = handle_spotify_exception(sp.user_playlists, user_id, limit=50)

    while user_playlists:
        for item in user_playlists["items"]:
            if re.search(r"^BPM [0-9][0-9]?[0-9]?$", item["name"]):
                bpm = int(re.search(r"[0-9][0-9]?[0-9]?", item["name"]).group())
                #print(bpm)
                if bpm not in bpm_playlists.keys():
                    bpm_playlists[bpm] = item["id"]
                    #print(item["id"])
            else:
                non_bpm_playlists.append(item["id"])
        user_playlists = handle_spotify_exception(sp.next, user_playlists) if user_playlists["next"] else None

def get_playlist_tracks(id):
    results = handle_spotify_exception(sp.playlist_tracks, id, fields="items.track.id,next", limit=100, additional_types=('track'))
    track_ids = []
    while results:
        for track in results["items"]:
            track_ids.append(track["track"]["id"])
        results = handle_spotify_exception(sp.next, results) if results["next"] else None
    return track_ids

# go through playlists and get tracks 
# get_tracks_playlist
# while tracks:
# for item in tracks
#   get_track bpm

def safe_add_tracks(sp, playlist_id, track_uris):
    batch_size = 100
    for i in range(0, len(track_uris), batch_size):
        batch = track_uris[i:i + batch_size]
        while True:
            try:
                sp.playlist_add_items(playlist_id, batch)
                break
            except SpotifyException as e:
                if e.http_status == 429:
                    retry_after = int(e.headers.get("Retry-After", 5))
                    print(f"⚠️ Rate limited. Retrying in {retry_after} seconds...")
                    time.sleep(retry_after)
                else:
                    raise  # re-raise other errors

def remove_duplicates(playlist_track_ids, new_tracks):
    playlist_set = set(playlist_track_ids)
    return list(set(new_tracks) - playlist_set)

def sort_songs_by_exact_bpm():
    liked_songs = get_liked_songs()
    #liked_songs = get_x_liked_songs(30)

    categorized_tracks = {}
    
    for track_id, track_name in liked_songs:
        bpm = get_track_bpm(track_id)
        
        if bpm == 0:
            print(f"No acousticbrainz BPM for: {track_name} ({track_id})")
        
        if bpm not in categorized_tracks:
            categorized_tracks[bpm] = []
        
        categorized_tracks[bpm].append(track_id)
    
    for bpm, tracks in categorized_tracks.items():
        playlist_name = f"BPM {bpm}"
        playlist_id = get_or_create_playlist(playlist_name, bpm)
        if playlist_id not in track_dictionary.keys():
            track_dictionary[playlist_id] = get_playlist_tracks(playlist_id)

        unique_new_tracks = remove_duplicates(track_dictionary[playlist_id], tracks)
        if unique_new_tracks:
            safe_add_tracks(sp, playlist_id, unique_new_tracks)
            print(f"Added {len(unique_new_tracks)} songs to {playlist_name}")
        else:
            print(f"⚠️ Skipping playlist {playlist_id} — no new tracks to add.")
        
        #print(bpm_playlists)
        #print(track_dictionary)

def print_first_few_tracks():
    liked_songs = get_liked_songs()
    for track in liked_songs[:10]:
        print(f"ID: {track[0]} Title: {track[1]} Artist: {track[2]} Album: {track[3]}")
        print(get_track_bpm(track[0]))



#print_first_few_tracks()
retrieve_playlists()
sort_songs_by_exact_bpm()
