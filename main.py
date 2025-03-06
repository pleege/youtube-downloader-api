#!/usr/bin/env python
# coding=utf8
import logging
import yt_dlp  # 替换pytube为yt-dlp
from flask import Flask, request, jsonify, g, stream_with_context, Response, url_for
import time
import tempfile
import os
import shutil
import sys
from tqdm import tqdm

# 配置日志记录
def setup_logging():
    """配置日志记录器"""
    logger = logging.getLogger(__name__)
    
    # 设置日志级别
    logger.setLevel(logging.DEBUG)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    
    # 设置日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    # 添加处理器到日志记录器
    logger.addHandler(console_handler)
    
    return logger

# 创建日志记录器
logger = setup_logging()

app = Flask(__name__)

# 添加请求前钩子，记录开始时间
@app.before_request
def before_request():
    g.start_time = time.time()

# 添加请求后钩子，记录处理时间
@app.after_request
def after_request(response):
    if hasattr(g, 'start_time'):
        elapsed_time = time.time() - g.start_time
        # 只对非流式响应记录处理时间
        if not response.direct_passthrough:
            logger.info(f"请求: {request.path} | 状态码: {response.status_code} | 处理时间: {elapsed_time:.3f}秒")
    return response

# 添加全局变量来存储下载状态
download_stats = {}

# 添加全局变量来跟踪进度条状态
_transfer_progress_bar = None

@app.teardown_request
def teardown_request(exception=None):
    """在请求结束时清理资源"""
    global _transfer_progress_bar
    
    # 清理进度条
    if _transfer_progress_bar:
        _transfer_progress_bar.close()
        _transfer_progress_bar = None
    
    # 清理下载统计信息
    if request.endpoint == 'youtube_download' and request.path in download_stats:
        stats = download_stats[request.path]
        if not stats.get('completed', False):  # 只有在未完成时才记录
            logger.info(f"下载请求被中断 - 路径: {request.path}")
        del download_stats[request.path]  # 清理统计信息

def generate_file(temp_path, request_path, video_id):
    global _transfer_progress_bar
    chunk_size = 8192
    file_size_local = os.path.getsize(temp_path)
    bytes_sent = 0
    start_time = time.time()
    
    # 确保之前的进度条被清理
    if _transfer_progress_bar:
        _transfer_progress_bar.close()
        _transfer_progress_bar = None
    
    # 创建新的进度条
    _transfer_progress_bar = tqdm(
        total=file_size_local,
        unit='B',
        unit_scale=True,
        ascii=True,
        ncols=80,
        mininterval=0.1,
        desc=f"传输进度 [{video_id}]"
    )
    
    try:
        with open(temp_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                bytes_sent += len(chunk)
                if _transfer_progress_bar:
                    _transfer_progress_bar.update(len(chunk))
                yield chunk

        # 传输完成后记录统计信息
        end_time = time.time()
        total_time = end_time - start_time
        avg_speed = file_size_local / total_time / (1024 * 1024)
        
        # 关闭并清理进度条
        if _transfer_progress_bar:
            _transfer_progress_bar.close()
            _transfer_progress_bar = None
        
        logger.info(
            f"下载请求完成 - ID: {video_id} | "
            f"路径: {request_path} | "
            f"传输文件大小: {file_size_local/1024/1024:.2f}MB | "
            f"总用时: {total_time:.2f}秒 | "
            f"平均传输速度: {avg_speed:.2f}MB/s"
        )
        
        # 标记为已完成
        if request_path in download_stats:
            download_stats[request_path]['completed'] = True
            
    except GeneratorExit:
        if _transfer_progress_bar:
            _transfer_progress_bar.close()
            _transfer_progress_bar = None
        logger.info(f"下载被客户端中断 - ID: {video_id} | "
                   f"路径: {request_path} | "
                   f"已传输: {bytes_sent/1024/1024:.2f}MB")
        raise

# 使用 yt-dlp 获取 YouTube 视频信息
def get_video_info(url):
    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4][vcodec!=none]',  
            'quiet': True,
            'no_warnings': True,
            'cookiefile': 'cookies.txt',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            def get_size(f):
                if not f:
                    return float('inf')
                filesize = f.get('filesize')
                if filesize is not None:
                    return filesize
                filesize_approx = f.get('filesize_approx')
                if filesize_approx is not None:
                    return filesize_approx
                return float('inf')
            
            video_formats = [f for f in formats if f.get('vcodec') != 'none']
            
            logger.info(f"找到 {len(video_formats)} 个视频格式")
            
            for f in video_formats:
                height = f.get('height')
                if not height:
                    resolution = f.get('resolution', '')
                    if 'x' in resolution:
                        height = int(resolution.split('x')[1])
                
                logger.info(f"可用视频格式: ID={f.get('format_id')}, "
                          f"分辨率={height}p, "
                          f"编码={f.get('vcodec')}, "
                          f"音频={f.get('acodec')}, "
                          f"大小={get_size(f)/(1024*1024):.2f}MB")
            
            resolutions = [1080, 720, 480, 360]
            selected_video_format = None
            
            for res in resolutions:
                matching_formats = [
                    f for f in video_formats 
                    if (f.get('height') == res or 
                        (f.get('resolution', '').endswith(f'x{res}') or 
                         f.get('resolution', '').startswith(f'{res}x')))
                ]
                if matching_formats:
                    logger.info(f"找到 {len(matching_formats)} 个 {res}p 格式")
                    mp4_formats = [f for f in matching_formats if f.get('ext', '').lower() == 'mp4']
                    if mp4_formats:
                        selected_video_format = mp4_formats[0]
                        logger.info(f"选择 {res}p 格式，扩展名为 mp4")
                        break
            
            if not selected_video_format:
                logger.error("未找到合适的视频格式")
                return {
                    'errcode': 901, 
                    'msg': "未找到合适的视频格式"
                }
            
            audio_formats = [
                f for f in formats 
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none'
            ]
            
            logger.info(f"找到 {len(audio_formats)} 个音频格式")
            
            selected_audio_format = None
            if audio_formats:
                def get_audio_quality(f):
                    tbr = f.get('tbr', 0)
                    return tbr if tbr is not None else 0
                
                selected_audio_format = max(audio_formats, key=get_audio_quality)
            
            if not selected_audio_format:
                logger.error("未找到合适的音频格式")
                return {
                    'errcode': 902, 
                    'msg': "未找到合适的音频格式"
                }
            
            video_size = get_size(selected_video_format)
            audio_size = get_size(selected_audio_format)
            total_size = video_size + audio_size
            
            format_string = f"{selected_video_format['format_id']}+{selected_audio_format['format_id']}"
            
            logger.info(f"选择的视频格式: "
                        f"ID={selected_video_format.get('format_id')} | "
                        f"分辨率={selected_video_format.get('height')}p | "
                        f"大小={video_size/(1024*1024):.2f}MB")
            logger.info(f"选择的音频格式: "
                        f"ID={selected_audio_format.get('format_id')} | "
                        f"比特率={selected_audio_format.get('tbr')}kbps | "
                        f"大小={audio_size/(1024*1024):.2f}MB")
            logger.info(f"预计总文件大小: {total_size/(1024*1024):.2f}MB")
            logger.info(f"最终下载格式字符串: {format_string}")
            
            player_url = url_for('youtube_download', id=info.get('id'), format=format_string, _external=True)
            
            upload_date = info.get('upload_date', '')
            formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]} 00:00:00" if upload_date else ""
            
            video_info = {
                'errcode': 0,
                'msg': "ok",
                'title': info.get('title', ''),
                'vid': info.get('id', ''),
                'author': info.get('uploader', ''),
                'published_date': formatted_date,
                'duration': info.get('duration', 0),
                'views': info.get('view_count', 0),
                'description': info.get('description', ''),
                'thumbnail': info.get('thumbnail', ''),
                'watch_url': url,
                'player_url': player_url,
                'format': format_string,
                'size': total_size,
                'size_mb': round(total_size / (1024 * 1024), 2)
            }
            return video_info
    except Exception as e:
        logger.error(f"解析视频信息时发生错误: {str(e)}", exc_info=True)
        return {'errcode': 900, 'msg': f"解析youtube视频信息失败, 错误信息: {str(e)}"}

# 获取推特视频信息
def get_twitter_video_info(url):
    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            formats = info.get('formats', [])
            best_format = next(
                (f for f in reversed(formats) if f.get('acodec') != 'none' and f.get('vcodec') != 'none'), None)
            player_url = best_format['url'] if best_format else None
            upload_date = info.get('upload_date', '')
            formatted_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]} 00:00:00" if upload_date else ""

            video_info = {
                'errcode': 0,
                'msg': "ok",
                'title': info.get('title', ''),
                'vid': info.get('id', ''),
                'author': info.get('uploader', ''),
                'published_date': formatted_date,
                'duration': info.get('duration', 0),
                'views': info.get('view_count', 0),
                'description': info.get('description', ''),
                'thumbnail': info.get('thumbnail', ''),
                'watch_url': url,
                'player_url': player_url
            }
            return video_info
    except Exception as e:
        return {'errcode': 900, 'msg': f"解析推特视频信息失败, 错误信息: {e}"}

@app.route("/youtube")
def youtube_info():
    video_id = request.args.get("id")
    url = f"https://www.youtube.com/watch?v={video_id}"
    video_info = get_video_info(url)
    return jsonify(video_info)

@app.route("/twitter")
def twitter_info():
    url = request.args.get("url")
    if not url:
        return jsonify({'errcode': 400, 'msg': "缺少url参数"})
    
    if "twitter.com" in url or "x.com" in url:
        video_info = get_twitter_video_info(url)
        return jsonify(video_info)
    else:
        return jsonify({'errcode': 400, 'msg': "无效的推特URL"})

@app.route("/youtube/download")
def youtube_download():
    temp_dir = None
    temp_path = None
    data = (request.get_json() or request.form) if request.method == 'POST' else {}
    video_id = data.get("id") or request.args.get("id")
    format_str = data.get("format") or request.args.get("format")

    try:
        if not video_id:
            return jsonify({'errcode': 400, 'msg': "缺少视频ID参数"})
        if not format_str:
            return jsonify({'errcode': 400, 'msg': "缺少format参数"})

        url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"开始处理YouTube视频下载请求 - ID: {video_id} | URL: {url} | 格式: {format_str}")

        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, f"{video_id}.mp4")
        logger.info(f"创建临时目录 - ID: {video_id} | 路径: {temp_dir}")
        
        def progress_hook(d):
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes', 0) or 0
            speed = d.get('speed', 0)
            
            if not hasattr(progress_hook, 'pbar'):
                progress_hook.pbar = tqdm(
                    total=total,
                    unit='B',
                    unit_scale=True,
                    desc=f"下载进度 [{video_id}]",
                    ncols=80,
                    ascii=True,
                    mininterval=0.1,
                    dynamic_ncols=False,
                    file=sys.stderr
                )
            
            increment = downloaded - progress_hook.pbar.n
            if increment > 0:
                progress_hook.pbar.update(increment)
                progress_hook.pbar.refresh()
            
            if d.get('status') == 'finished':
                progress_hook.pbar.close()
                delattr(progress_hook, 'pbar')
        
        ydl_opts = {
            'format': format_str,
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'outtmpl': temp_path,
            'progress_hooks': [progress_hook],
            'cookiefile': 'cookies.txt',
            'logger': None,
            'no_color': True
        }

        start_time = time.time()
        logger.info("开始下载视频...")
            
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError as e:
            if "Sign in to confirm you're not a bot" in str(e):
                return jsonify({
                    'errcode': 403, 
                    'msg': "需要YouTube授权，请确保已正确配置cookies.txt文件"
                })
            raise

        file_size = os.path.getsize(temp_path)
        download_time = time.time() - start_time
        avg_speed = file_size / (1024 * 1024 * download_time) if download_time > 0 else 0
            
        logger.info(f"视频下载完成: 文件大小={file_size/1024/1024:.2f}MB, 用时={download_time:.2f}秒, 平均速度={avg_speed:.2f}MB/s")

        response = Response(
            stream_with_context(generate_file(temp_path, request.path, video_id)),
            mimetype='video/mp4'
        )
        response.headers['Content-Disposition'] = f'attachment; filename="{video_id}.mp4"'
        response.headers['Content-Length'] = os.path.getsize(temp_path)

        return response

    except Exception as e:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        error_msg = str(e).split('\n')[0]
        logger.error(f"视频下载失败 - ID: {video_id} | 错误: {error_msg}")
        return jsonify({'errcode': 900, 'msg': f"视频下载失败: {error_msg}"})

if __name__ == "__main__":
    # 禁用自动重载，避免文件变动时中断下载任务
    app.run(host="0.0.0.0", port=80, debug=True, use_reloader=True)



# pot: MluaqJzwZJwropqQCHKuJi2nOQBq_C2OzhPbBh-MnJRLOGrL2gxhPH93CjDrU4E8ssqAQIKL7rlTPl_rh8zFTCQJSdkTUdVlwk7qxRlYXdtgEghMRmHvn96_CPfT