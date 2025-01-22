from http.server import BaseHTTPRequestHandler, HTTPServer
import cgi
import os
import shutil
import mimetypes
import time
from pathlib import Path
import threading
import yaml
import socket
from tqdm import tqdm
import urllib

from merge_videos import process_a_video, merge_videos


# To avoid printing HTTP requests
def log_message(self, format, *args):
    pass


BaseHTTPRequestHandler.log_message = log_message


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
        return lan_ip
    except Exception as e:
        print(f"Error obtaining LAN IP: {e}")
        return "???.???.???.???"


config = yaml.safe_load(open("config.yaml"))

# Shared progress variables
processing_lock = threading.Lock()
progress_lock = threading.Lock()
total_received = 0
total_completed = 0
total_files = 366

# TQDM progress bars
progress_bar_received = None
progress_bar_completed = None


def self_process_video(video_file, file_index):
    global total_completed, progress_bar_completed
    process_a_video(video_file, int(file_index), config)

    total_completed += 1
    progress_bar_completed.update(1)


def simulate_request_for_video(file_index):
    global total_received, progress_bar_received, progress_bar_completed

    os.makedirs("tmp/uploads", exist_ok=True)

    video_file = f"tmp/uploads/{file_index}.mp4"
    saved_video_file = f"saved/originals/{file_index}.mp4"
    shutil.copyfile(saved_video_file, video_file)

    if progress_bar_completed is None:
        progress_bar_received = tqdm(total=total_files, desc=" Received", position=0)
        progress_bar_completed = tqdm(total=total_files, desc="Completed", position=1)

    total_received += 1
    progress_bar_received.update(1)

    Path(video_file.replace(".mp4", ".lock")).touch()
    self_process_video(video_file, file_index)


def simulate_request_for_merge():

    file_path = "tmp/combined_video.mp4"

    if progress_bar_received:
        progress_bar_received.close()
        progress_bar_completed.close()

    Path("tmp/process.lock").touch()
    merge_videos(
        **{
            "config": config,
            "output_combined_video": file_path,
            "delete_intermediate_files": config["delete_intermediate_files"],
            "lossless": config["lossless"],
        }
    )

    # Clean up

    if (save_path := config["save_result_to"]) is not None:
        os.makedirs(save_path, exist_ok=True)
        shutil.copyfile("tmp/combined_video.mp4", f"{save_path}/result.mp4")

    if config["delete_intermediate_files"]:
        for file in os.listdir("tmp/uploads"):
            os.remove(f"tmp/uploads/{file}")
        os.remove("tmp/combined_video.mp4")
        os.rmdir("tmp/uploads")
        os.rmdir("tmp")


def run():
    for i in range(1, 367):
        simulate_request_for_video(i)
    simulate_request_for_merge()


if __name__ == "__main__":
    print("Using config:")
    for key, value in config.items():
        print(f"\t{key}: {value}")
    print()

    try:
        run()
    except KeyboardInterrupt:
        progress_bar_received.close()
        progress_bar_completed.close()
