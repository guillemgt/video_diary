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
        ['ffprobe', '-v', '0', '-select_streams', 'v:0', '-show_entries', 'stream_side_data=rotation', '-of', 'default=nw=1:nk=1', input_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    rotation = 0
    output = result.stdout.decode().strip()
    try:
        rotation = int(output)
    except ValueError:
        pass
    return rotation

def set_to_8_bit_encoding_if_necessary(input_path, delete_intermediate_files=True):
    # Check if the video is already in 8-bit encoding
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=profile', '-of', 'default=nw=1:nk=1', input_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    profile = result.stdout.decode().strip()
    if '10' in profile:
        # Convert to 8-bit encoding
        output_path = input_path.replace('.mp4', '_8bit.mp4')
        ffmpeg_command = [
            'ffmpeg', '-y', '-i', input_path, '-vf', 'format=yuv420p', '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', '-c:a', 'copy', output_path
        ]
        subprocess.run(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if delete_intermediate_files:
            os.remove(input_path)
        return output_path
    return input_path

def process_video(input_path, output_path, target_width, target_height, text,
                  framerate=30, font='Arial', fontsize=100, bevel=None, delete_intermediate_files=True, lossless=True):
    
    if bevel is None:
        bevel = fontsize // 30
    
    input_path = set_to_8_bit_encoding_if_necessary(input_path, delete_intermediate_files=delete_intermediate_files)

    # Get the original dimensions and rotation of the video
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', input_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    width, height = map(int, result.stdout.decode().strip().split(',')[:2])

    rotation = get_video_rotation(input_path)

    # Adjust dimensions based on rotation
    if rotation in [90, -90, 270, -270]:
        width, height = height, width

    # print(width, height, rotation)

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

    # Define codec settings based on the lossless argument
    if lossless != False:
        video_codec = ['-c:v', 'h264_nvenc', '-qp', '0' if lossless == True else str(lossless-1)]
    else:
        video_codec = ['-c:v', 'h264_nvenc']

    # Convert to constant frame rate, normalize, resize, pad, and add text using ffmpeg with hardware acceleration
    ffmpeg_command = [
        'ffmpeg',
        '-y',
        '-hwaccel', 'cuda',
        '-i', input_path, '-vf',
        f"fps={framerate},{scale_filter},{pad_filter},{draw_text_filter}",
        *video_codec, '-c:a', 'copy', output_path
    ]
    
    result = subprocess.run(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if result.returncode != 0:
        print(f"Error processing video {input_path}: {result.stderr.decode()}")
        raise RuntimeError(f"ffmpeg command failed with return code {result.returncode}")
    
    if delete_intermediate_files and input_path != output_path:
        os.remove(input_path)

        
        
def format_date_no_leading_zero(date):
    # This function removes leading zeros from the day
    return date.strftime('%-d %b %Y') if os.name != 'nt' else date.strftime('%#d %b %Y')

def process_a_video(input_file, index, config):
    start_date = datetime(config['start_year'], config['start_month'], config['start_day'])
    common_width = config['width']
    common_height = config['height']
    framerate = config['framerate']
    lossless = config['lossless_aux']
    delete_intermediate_files = config['delete_intermediate_files']
    font = config['font']
    fontsize = config['font_size']

    date = (start_date + timedelta(days=index-1))
    date = format_date_no_leading_zero(date)
    output_file = input_file.replace('.mp4', '_processed.mp4')
    process_video(input_file, output_file,
        target_width=common_width,
        target_height=common_height,
        text=date,
        framerate=framerate,
        lossless=lossless,
        delete_intermediate_files=delete_intermediate_files,
        font=font,
        fontsize=fontsize
    )
    
    if os.path.exists(input_file.replace('.mp4', '.lock')):
        os.remove(input_file.replace('.mp4', '.lock'))

def merge_videos(
    folder_path = 'tmp/uploads',
    output_combined_video = 'tmp/combined_video.mp4',
    delete_intermediate_files = True,
    lossless=True
    ):
    
    video_files = [f for f in os.listdir(folder_path) if re.match(r'\d+_processed\.(mp4|MP4|mpd|MPD)', f)]
    video_files.sort(key=lambda f: int(re.match(r'(\d+)', f).group(1)))
    processed_files = []
    
    for i, video_file in enumerate(tqdm(video_files, desc='Adding dates')):
        processed_file = f'{folder_path}/{video_file}'
        processed_file = processed_file[len("tmp/"):]
        processed_files.append(processed_file)

    with open("tmp/videos_to_merge.txt", "w") as f:
        for video_file in processed_files:
            f.write(f"file '{video_file}'\n")
    
    # Use ffmpeg to merge the videos with hardware acceleration
    if lossless != False:
        video_codec = ['-c:v', 'h264_nvenc', '-qp', '0' if lossless == True else str(lossless-1)]
    else:
        video_codec = ['-c:v', 'h264_nvenc']
    ffmpeg_command = [
        "ffmpeg", '-y', "-loglevel", "quiet", "-hwaccel", "cuda", "-f", "concat", "-safe", "0", "-i", "tmp/videos_to_merge.txt",
        *video_codec, "-c:a", "copy", output_combined_video
    ]
    print('Running merge command:')
    print(' '.join(ffmpeg_command))
    result = subprocess.run(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if result.returncode != 0:
        print(f"Error merging videos: {result.stderr.decode()}")
        raise RuntimeError(f"ffmpeg merge command failed with return code {result.returncode}")
    
    if os.path.exists('tmp/process.lock'):
        os.remove('tmp/process.lock')
    
    if delete_intermediate_files:
        for video_file in processed_files:
            os.remove("tmp/" + video_file)
        os.remove("tmp/videos_to_merge.txt")



if __name__ == '__main__':
    merge_videos()