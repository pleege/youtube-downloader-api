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
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%m-%d %H:%M:%S'
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

# 修改请求后钩子，只对非流式响应记录处理时间
@app.after_request
def after_request(response):
    if hasattr(g, 'start_time'):
        elapsed_time = time.time() - g.start_time
        # 只对非流式响应记录处理时间
        if not response.direct_passthrough:  # 普通响应
            # logger.info(f"请求: {request.path} | 状态码: {response.status_code} | 处理时间: {elapsed_time:.3f}秒")
            pass
    return response

# 添加全局变量来存储下载状态
download_stats = {}

# 添加全局变量来跟踪进度条状态
_transfer_progress_bar = None

# 添加新的请求完成钩子
@app.teardown_request
def teardown_request(exception=None):
    """在请求完全结束时（包括流式传输完成后）清理资源"""
    global _transfer_progress_bar
    
    # 清理进度条
    if _transfer_progress_bar:
        _transfer_progress_bar.close()
        _transfer_progress_bar = None
    
    # 清理下载统计信息
    if request.endpoint == 'youtube_download' and request.path in download_stats:
        stats = download_stats[request.path]
        if stats.get('completed', False):  # 只在成功完成时记录
            logger.info(f"数据传输已完成 - 路径: {request.path}")
        else:
            logger.info(f"下载请求被中断 - 路径: {request.path}")
        del download_stats[request.path]  # 清理统计信息

def generate_file(temp_path, request_path, video_id):
    global _transfer_progress_bar
    chunk_size = 8192
    file_size_local = os.path.getsize(temp_path)
    bytes_sent = 0
    start_time = time.time()
    first_chunk_sent = False
    progress_bar_initialized = False
    
    # 确保之前的进度条被清理
    if _transfer_progress_bar:
        _transfer_progress_bar.close()
        _transfer_progress_bar = None
    
    # 先记录传输开始的统计信息
    logger.info(
        f"开始文件传输 - ID: {video_id} | "
        f"路径: {request_path} | "
        f"文件大小: {file_size_local/1024/1024:.2f}MB"
    )
    
    try:
        with open(temp_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                
                # 先发送第一个数据块
                if not first_chunk_sent:
                    first_chunk_sent = True
                    bytes_sent += len(chunk)
                    yield chunk
                    continue
                
                # 在第二个数据块之前初始化进度条
                if not progress_bar_initialized and file_size_local > 0:  # 添加文件大小检查
                    _transfer_progress_bar = tqdm(
                        total=file_size_local,
                        unit='B',
                        unit_scale=True,
                        ascii=True,  # 改用 ASCII 字符而不是 Unicode
                        ncols=90,
                        mininterval=0.1,
                        desc=f"传输进度 [{video_id}]",
                        leave=True,
                        bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} ({rate_fmt}) [{elapsed}]'
                    )
                    # 更新已发送的第一个数据块的进度
                    _transfer_progress_bar.update(bytes_sent)
                    progress_bar_initialized = True
                
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

        # 使用固定的临时目录
        temp_dir = "/tmp/youtube"
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        temp_path = os.path.join(temp_dir, f"{video_id}.mp4")
        logger.info(f"使用临时目录 - ID: {video_id} | 路径: {temp_dir}")

        # 修改进度条逻辑
        progress_bar = None
        total_bytes = 0
        current_file = None
        downloaded_streams = set()  # 用于跟踪已下载完成的流
        
        def progress_hook(d):
            nonlocal progress_bar, total_bytes, current_file, downloaded_streams
            
            if d['status'] == 'downloading':
                # 获取当前下载的文件信息
                format_id = d.get('info_dict', {}).get('format_id', '')
                vcodec = d.get('info_dict', {}).get('vcodec', '')
                acodec = d.get('info_dict', {}).get('acodec', '')
                
                # 判断是视频流还是音频流
                stream_type = "视频" if vcodec != 'none' else "音频" if acodec != 'none' else "未知"
                
                # 如果是新的文件，更新进度条
                if format_id != current_file:
                    current_file = format_id
                    if progress_bar:
                        progress_bar.close()
                    total_bytes = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                    progress_bar = tqdm(
                        total=total_bytes,
                        unit='B',
                        unit_scale=True,
                        desc=f"下载{stream_type}流 [{video_id}] (格式: {format_id})",
                        ncols=90,
                        ascii=True,
                        mininterval=0.1,
                        bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} ({rate_fmt}) [{elapsed}]'
                    )
                
                # 更新进度
                if progress_bar:
                    downloaded = d.get('downloaded_bytes', 0)
                    progress_bar.update(downloaded - progress_bar.n)
            
            elif d['status'] == 'finished':
                if progress_bar:
                    progress_bar.close()
                    progress_bar = None
                
                # 记录已完成的流
                if current_file:
                    downloaded_streams.add(current_file)
                    
                # 如果是分开的视频和音频流，检查是否都已下载完成
                if '+' in format_str:
                    expected_streams = set(format_str.split('+'))
                    if downloaded_streams == expected_streams:
                        logger.info("开始合并MP4视频...")
        
        ydl_opts = {
            'format': format_str,
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,  # 禁用内置进度条显示
            'outtmpl': temp_path,
            'progress_hooks': [progress_hook],
            'cookiefile': 'cookies.txt',
        }

        start_time = time.time()
        logger.info("开始下载视频...")
            
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError as e:
            error_str = str(e).lower()  # 转换为小写以进行更可靠的匹配
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            if "sign in to confirm" in error_str:  # 简化匹配条件
                logger.error(f"YouTube需要授权访问,可能cookies.txt文件配置错误")
                return jsonify({
                    'errcode': 403,
                    'msg': "需要YouTube授权，请联系管理员!"
                })
            else:
                # 直接返回下载错误，而不是raise
                logger.error(f"下载错误 - ID: {video_id} | 错误: {str(e)}")
                return jsonify({
                    'errcode': 901,
                    'msg': f"视频下载失败: {str(e).split('\n')[0]}"
                })
            
        file_size = os.path.getsize(temp_path)
        download_time = time.time() - start_time
        avg_speed = file_size / (1024 * 1024 * download_time) if download_time > 0 else 0
            
        logger.info(f"视频合并完成: 文件大小={file_size/1024/1024:.2f}MB, 用时={download_time:.2f}秒, 平均速度={avg_speed:.2f}MB/s")

        def cleanup():
            try:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
                    logger.info(f"已清理临时文件 - ID: {video_id} | 路径: {temp_path}")
            except Exception as e:
                logger.error(f"清理临时文件失败 - ID: {video_id} | 错误: {str(e)}")

        response = Response(
            stream_with_context(generate_file(temp_path, request.path, video_id)),
            mimetype='video/mp4'
        )
        response.headers['Content-Disposition'] = f'attachment; filename="{video_id}.mp4"'
        response.headers['Content-Length'] = os.path.getsize(temp_path)
        
        # 注册回调函数，在响应结束后清理文件
        response.call_on_close(cleanup)

        return response

    except Exception as e:
        # 发生错误时也要清理临时文件
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.info(f"已清理临时文件 - ID: {video_id} | 路径: {temp_path}")
            except Exception as cleanup_error:
                logger.error(f"清理临时文件失败 - ID: {video_id} | 错误: {str(cleanup_error)}")
        
        logger.error(f"视频下载失败 - ID: {video_id} | 错误: {str(e)}", exc_info=True)
        return jsonify({'errcode': 900, 'msg': f"视频下载失败: {str(e)}"})

if __name__ == "__main__":
    # 清理并重建临时目录
    temp_dir = "/tmp/youtube"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    logger.info(f"-----已清理并重建临时目录: {temp_dir}")
    
    # 禁用自动重载，避免文件变动时中断下载任务
    app.run(host="0.0.0.0", port=80, debug=True, use_reloader=True)




        