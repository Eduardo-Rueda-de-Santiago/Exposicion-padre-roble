import os

import gdown

# Google Drive folder URL
url = "https://drive.google.com/drive/folders/1DDeWFLnZfDH5vlemD7cmX1ti41YLLDkX"

# Destination directory
videos_dir = "videos"

if not (os.path.exists("videos/ProyFinal_Centro_AUDIO.mp4")) and not (
    os.path.exists("videos/ProyFinal_Derecha_AUDIO.mp4")
):
    # Create directory if it doesn't exist
    os.makedirs(videos_dir, exist_ok=True)

    # Download all files from the folder
    gdown.download_folder(url=url, output=videos_dir, quiet=False, use_cookies=False)

    print("Download complete.")
else:
    print("Los vídeos ya existen")
