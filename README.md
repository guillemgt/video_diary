# Video Diary

A free user-unfriendly alternative to [1 Second Everyday](https://apps.apple.com/us/app/1-second-everyday-diary/id587823548) for iOS.

The program combines the videos in an iOS album, adds dates sequentially to the bottom left of the video, and puts all the videos together chronologically.
An iOS shortcut sends the videos over to a Python server, which process them and combines them, and then sends the output video back.

NOTE: The dates in the videos are not the actual dates on which the videos where recorded! Instead, the first video has the date set in the config file and each subsequent video has the date for the following day.


## Installation

The server script requires Python and `ffmpeg` to be installed.

Download [the iOS shorcut](https://www.icloud.com/shortcuts/f42337bf98c4483b86ab8b235d198d40) and install it on your iOS device.

## Usage

Change the settings in `congif.yaml` to the desired settings.
Start the server with
```
python server.py
```

Edit the iOS shortcut and change the album in the first block to the desired album.
Run the shortcut and copy the server address when prompted.
When the shortcut finishes running, the output video will be saved to your gallery.