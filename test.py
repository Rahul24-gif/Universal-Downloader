import sys
import yt_dlp
import traceback

def test():
    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    opts = {
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        },
        'quiet': False,
        'no_warnings': False,
        'noplaylist': True,
        'nocheckcertificate': True,
        'verbose': True
    }
    print("Testing yt-dlp fetch...")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=False)
        print("Success!")
    except Exception as e:
        print("Error:")
        traceback.print_exc()

if __name__ == "__main__":
    test()
