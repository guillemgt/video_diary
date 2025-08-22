import os
import re
import time
from datetime import datetime, timedelta
from tqdm import tqdm
import subprocess
import json


def get_video_rotation(input_path):
    # Extract rotation information from ffprobe output
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "0",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream_side_data=rotation",
            "-of",
            "default=nw=1:nk=1",
            input_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    rotation = 0
    output = result.stdout.decode().strip()
    try:
        rotation = int(output)
    except ValueError:
        pass
    return rotation


def deal_with_8bit_encoding_and_hdr(input_path, delete_intermediate_files=True):
    """
    Check if a video is in HDR and convert it to SDR if necessary.
    """

    # Check video metadata with ffprobe
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=color_primaries,color_transfer,color_space,max_cll,master_display",
            "-of",
            "json",
            input_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    metadata = json.loads(result.stdout.decode())

    # Extract color metadata
    stream_metadata = metadata.get("streams", [{}])[0]
    color_primaries = stream_metadata.get("color_primaries", "")
    color_transfer = stream_metadata.get("color_transfer", "")
    color_space = stream_metadata.get("color_space", "")

    # Adjust parameters for HDR input
    if (
        color_primaries == "bt2020"
        or color_transfer in ["smpte2084", "arib-std-b67"]
        or color_space == "bt2020_ncl"
    ):
        output_path = input_path.replace(".mp4", "_sdr.mp4")

        # Construct the ffmpeg command
        vf_filters = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"

        ffmpeg_command = [
            "ffmpeg",
            "-i",
            input_path,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-vf",
            vf_filters,
            "-colorspace",
            "bt709",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "slow",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            output_path,
        ]

        # Print and execute the command
        # print("FFmpeg command:", ' '.join(ffmpeg_command))
        result = subprocess.run(
            ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        if result.returncode != 0:
            print("Error during FFmpeg execution:")
            print(result.stderr.decode())
            raise RuntimeError("FFmpeg failed to execute the tone mapping process.")

        # Optionally delete the original file
        if delete_intermediate_files:
            os.remove(input_path)
        return output_path
    return input_path


def add_empty_audio_if_missing(input_path, delete_intermediate_files=True):
    """
    Adds a silent audio track to a video if it doesn't have one.
    """

    # Check if the input video has an audio stream
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            input_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not result.stdout.strip():
        # No audio stream found; add a silent audio track
        video_duration = (
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    input_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            .stdout.decode()
            .strip()
        )

        output_path = input_path.replace(".mp4", "_with_audio_stream.mp4")
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-f",
                "lavfi",
                "-t",
                video_duration,
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                output_path,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if result.returncode != 0:
            print("Error during FFmpeg execution for adding empty audio stream:")
            print(result.stderr.decode())
            raise RuntimeError("FFmpeg failed to execute the audio addition process.")

        # Optionally delete the original file
        if delete_intermediate_files:
            os.remove(input_path)
        return output_path
    else:
        # If audio exists, just copy the input to the output
        return input_path


def process_video(
    input_path,
    output_path,
    target_width,
    target_height,
    text,
    framerate=30,
    font="Arial",
    fontsize=100,
    bevel=None,
    delete_intermediate_files=True,
    lossless=True,
    force_video_duration_to_seconds=None,
):
    if bevel is None:
        bevel = fontsize // 30

    # Step 1: Handle missing audio
    input_path = add_empty_audio_if_missing(
        input_path, delete_intermediate_files=delete_intermediate_files
    )

    # Step 2: Handle HDR
    input_path = deal_with_8bit_encoding_and_hdr(
        input_path, delete_intermediate_files=delete_intermediate_files
    )

    # Step 3: Normalize dimensions and aspect ratio

    # Get the original dimensions and rotation of the video
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            input_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    width, height = map(int, result.stdout.decode().strip().split(",")[:2])

    rotation = get_video_rotation(input_path)

    # Adjust dimensions based on rotation
    if rotation in [90, -90, 270, -270]:
        width, height = height, width

    # Calculate the scaling factors and padding to preserve aspect ratio
    aspect_ratio = width / height
    target_aspect_ratio = target_width / target_height

    if aspect_ratio > target_aspect_ratio:
        # Scale to target width
        scale_width = target_width
        scale_height = int(target_width / aspect_ratio)
    else:
        # Scale to target height
        scale_height = target_height
        scale_width = int(target_height * aspect_ratio)

    pad_width = (target_width - scale_width) // 2
    pad_height = (target_height - scale_height) // 2

    scale_filter = f"scale={scale_width}:{scale_height}"
    pad_filter = f"pad={target_width}:{target_height}:{pad_width}:{pad_height}:black"
    position = (fontsize // 5, -(fontsize // 5))
    draw_text_filter = (
        f"drawtext=text='{text}':fontfile={font}:fontsize={fontsize}:fontcolor=black:"
        f"x={position[0]+bevel}:y={position[1]+bevel}+h-th,"
        f"drawtext=text='{text}':fontfile={font}:fontsize={fontsize}:fontcolor=white:"
        f"x={position[0]}:y={position[1]}+h-th"
    )
    normalized_fps_filter = f"fps={framerate}"

    # Step 4: Define codec settings based on the lossless argument
    if lossless != False:
        video_codec = [
            "-c:v",
            "h264_nvenc",
            "-qp",
            "0" if lossless == True else str(lossless - 1),
        ]
    else:
        video_codec = ["-c:v", "h264_nvenc"]

    # Step 5: Define duration arguments if necessary
    duration_args = (
        []
        if force_video_duration_to_seconds is None
        else ["-t", str(force_video_duration_to_seconds)]
    )

    # Step 6: Combine normalization, scaling, and audio in a single FFmpeg command
    ffmpeg_command = [
        "ffmpeg",
        "-y",
        "-hwaccel",
        "cuda",
        "-i",
        input_path,
        "-vf",
        f"{normalized_fps_filter},{scale_filter},{pad_filter},{draw_text_filter}",
        *video_codec,
        *duration_args,
        "-vsync",
        "cfr",
        "-r",
        str(framerate),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        output_path,
    ]

    result = subprocess.run(
        ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    if result.returncode != 0:
        print(f"Error processing video {input_path}: {result.stderr.decode()}")
        raise RuntimeError(
            f"ffmpeg command failed with return code {result.returncode}"
        )

    # Step 7: Cleanup intermediate files if necessary
    if delete_intermediate_files and input_path != output_path:
        os.remove(input_path)


def format_date_no_leading_zero(date):
    # This function removes leading zeros from the day
    return date.strftime("%-d %b %Y") if os.name != "nt" else date.strftime("%#d %b %Y")


def process_a_video(input_file, index, config):
    start_date = datetime(
        config["start_year"], config["start_month"], config["start_day"]
    )
    common_width = config["width"]
    common_height = config["height"]
    framerate = config["framerate"]
    lossless = config["lossless_aux"]
    delete_intermediate_files = config["delete_intermediate_files"]
    font = config["font"]
    fontsize = config["font_size"]

    date = start_date + timedelta(days=index - 1)
    date = format_date_no_leading_zero(date)
    output_file = input_file.replace(".mp4", "_processed.mp4")
    process_video(
        input_file,
        output_file,
        target_width=common_width,
        target_height=common_height,
        text=date,
        framerate=framerate,
        lossless=lossless,
        delete_intermediate_files=delete_intermediate_files,
        font=font,
        fontsize=fontsize,
        force_video_duration_to_seconds=config["force_video_duration_to_seconds"],
    )

    if os.path.exists(input_file.replace(".mp4", ".lock")):
        os.remove(input_file.replace(".mp4", ".lock"))


def merge_videos(
    config,
    folder_path="tmp/uploads",
    output_combined_video="tmp/combined_video.mp4",
    delete_intermediate_files=True,
    lossless=True,
):

    video_files = [
        f
        for f in os.listdir(folder_path)
        if re.match(r"\d+_processed\.(mp4|MP4|mpd|MPD)", f)
    ]
    video_files.sort(key=lambda f: int(re.match(r"(\d+)", f).group(1)))
    processed_files = []

    for i, video_file in enumerate(video_files):
        processed_file = f"{folder_path}/{video_file}"
        processed_file = processed_file[len("tmp/") :]
        processed_files.append(processed_file)

    with open("tmp/videos_to_merge.txt", "w") as f:
        for video_file in processed_files:
            f.write(f"file '{video_file}'\n")

    # Use ffmpeg to merge the videos with a consistent color format
    if lossless != False:
        video_codec = [
            "-c:v",
            "h264_nvenc",
            "-qp",
            "0" if lossless == True else str(lossless - 1),
        ]
    else:
        video_codec = ["-c:v", "h264_nvenc"]

    framerate = str(config["framerate"])
    ffmpeg_command = [
        "ffmpeg",
        "-y",
        "-hwaccel",
        "cuda",
        "-f",
        "concat",
        "-safe",
        "0",
        "-fflags",
        "+genpts",
        "-i",
        "tmp/videos_to_merge.txt",
        "-preset",
        "p5",
        "-vsync",
        "cfr",
        "-r",
        framerate,
        # Map video and audio explicitly
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        # # Reset timestamps
        # "setpts=PTS-STARTPTS",
        "-movflags",
        "+faststart",
        "-vf",
        f"format=yuv420p,fps={framerate}",
        *video_codec,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-async",
        "1",
        "-af",
        "aresample=async=1000",
        output_combined_video,
    ]
    print("\nRunning merge command:")
    print(" ".join(ffmpeg_command))
    result = subprocess.run(
        ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    if result.returncode != 0:
        print(f"Error merging videos: {result.stderr.decode()}")
        raise RuntimeError(
            f"ffmpeg merge command failed with return code {result.returncode}"
        )

    if os.path.exists("tmp/process.lock"):
        os.remove("tmp/process.lock")

    if delete_intermediate_files:
        for video_file in processed_files:
            os.remove("tmp/" + video_file)
        os.remove("tmp/videos_to_merge.txt")


if __name__ == "__main__":
    merge_videos()
