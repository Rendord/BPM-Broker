import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException
import time
import json
import requests
import urllib.parse

# Set up authentication
SPOTIPY_CLIENT_ID = "***REMOVED***"
SPOTIPY_CLIENT_SECRET = "***REMOVED***"
SPOTIPY_REDIRECT_URI = "http://127.0.0.1:3000"

MUSICBRAINZ_ENDPOINT = "https://musicbrainz.org/ws/2/recording/"
ACOUSTICBRAINZ_ENDPOINT = "https://acousticbrainz.org/api/v1/"

# Define the scopes needed
SCOPE = "user-library-read playlist-modify-public playlist-modify-private playlist-read-collaborative playlist-read-private user-read-email user-read-private user-read-playback-state user-read-currently-playing"

# Initialize Spotipy
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID,
                                               client_secret=SPOTIPY_CLIENT_SECRET,
                                               redirect_uri=SPOTIPY_REDIRECT_URI,
                                               scope=SCOPE))

# Get user ID
user_id = sp.me()["id"]

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

def get_liked_songs():
    songs = []
    results = handle_spotify_exception(sp.current_user_saved_tracks, limit=10)
    while results:
        for item in results["items"]:
            track = item["track"]
            #print(json.dumps(track, indent=4))
            artists = []
            for artist in track["artists"]:
                artists.append(artist["name"])
            songs.append((track["id"], track["name"], artists[0], track["album"]["name"]))
        results = sp.next(results) if results["next"] else None
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

def create_playlist(name):
    playlist = sp.user_playlist_create(user=user_id, name=name, public=False)
    return playlist["id"]

def sort_songs_by_exact_bpm():
    liked_songs = get_liked_songs()

    categorized_tracks = {}
    
    for track_id, track_name in liked_songs:
        bpm = get_track_bpm(track_id) #this is where i was at
        
        if bpm is None:
            print(f"Skipping track: {track_name} ({track_id})")
            continue
        
        bpm_category = f"BPM {round(bpm)}"
        if bpm_category not in categorized_tracks:
            categorized_tracks[bpm_category] = []
        
        categorized_tracks[bpm_category].append(track_id)
    
    for bpm_category, tracks in categorized_tracks.items():
        if tracks:
            playlist_id = create_playlist(bpm_category)
            sp.playlist_add_items(playlist_id, tracks)
            print(f"Added {len(tracks)} songs to {bpm_category}")

def print_first_few_tracks():
    
    liked_songs = get_liked_songs()
    for track in liked_songs[:10]:
        print(f"ID: {track[0]} Title: {track[1]} Artist: {track[2]} Album: {track[3]}")
        print(get_track_bpm(track[0]))



print_first_few_tracks()
#sort_songs_by_exact_bpm()
