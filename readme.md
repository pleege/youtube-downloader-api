# YouTube Downloader API

This project provides an API to download YouTube videos. It uses yt-dlp for video downloading and Flask for the API.

## Features

*   Download YouTube videos in various formats.
*   API endpoints for video information and download.
*   Dockerized for easy deployment.

## Requirements

*   Docker
*   Docker Compose (optional)

## Installation

1.  Clone the repository:

    ```bash
    git clone https://github.com/pleege/youtube-downloader-api.git
    cd youtube
    ```

2.  Build the Docker image:

    ```bash
    docker build -t ghcr.io/pleege/youtube . --force-rm --no-cache
    ```

## Usage

1.  Run the Docker container:

    ```bash
    docker run -itd --name youtube -v /path/to/cookies.txt:/deploy/cookies.txt -p 8809:80 ghcr.io/pleege/youtube
    ```

    *   `-v /path/to/cookies.txt:/deploy/cookies.txt`: Mount your `cookies.txt` file to the container. This is required for downloading age-restricted videos or videos that require login.
    *   `-p 8809:80`: Expose the port 80 on the container to port 8809 on the host.

2.  Access the API:

    *   Get video information:

        ```
        http://localhost:8809/youtube?id=<video_id>
        ```

    *   Download video:

        ```
        http://localhost:8809/youtube/download?id=<video_id>&format=<format_code>
        ```

## Configuration

*   `cookies.txt`: This file is used for authentication. You can generate it using `yt-dlp --cookies <your_youtube_url>`.
*   `supervisor.ini`: This file is used to manage the `main.py` process.
*   `entrypoint.sh`: This script is executed when the container starts. It checks if it's the first run and clones the repository or pulls the latest code.
*   `requirements.txt`: This file contains the Python dependencies.

## Dependencies

```
flask
yt_dlp
requests
tqdm
```

## Docker Compose (Optional)

1.  Create a `docker-compose.yaml` file:

    ```yaml
    version: "3.8"
    services:
      youtube:
        image: ghcr.io/pleege/youtube
        container_name: youtube
        volumes:
          - /path/to/cookies.txt:/deploy/cookies.txt
        ports:
          - "8809:80"
        restart: always
    ```

2.  Run the container using Docker Compose:

    ```bash
    docker-compose up -d
    ```

## Notes

*   Make sure to replace `/path/to/cookies.txt` with the actual path to your `cookies.txt` file.
*   The API exposes port 80, which is mapped to port 8809 on the host. You can change this mapping in the `docker run` command or `docker-compose.yaml` file.


```
# git clone https://github.com/pleege/youtube-downloader-api.git
# cd youtube-downloader-api
# docker build -t ghcr.io/pleege/youtube . --force-rm --no-cache

# docker run -itd --name youtube --restart always -v $(pwd)/cookies.txt:/deploy/cookies.txt -p 8809:80 ghcr.io/pleege/youtube
# 暴露目录可以方便远程调试
# docker run -itd --name youtube --restart always -v /home/ubuntu/youtube-downloader-api:/deploy -p 8809:80 ghcr.io/pleege/youtube 

# docker attach youtube
```
