import os
import requests
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip, TextClip, ColorClip
)
from moviepy.config import change_settings

change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})

def generate_sales_script(product_title, market_code):
    return (
        f"Você não vai acreditar no preço que eu achei dessa belezinha na Amazon! "
        f"A nova Alexa Echo Dot de quinta geração está com uma oferta absurda. "
        f"Ela tem o som muito mais potente, graves mais fortes e controla a sua casa inteira. "
        f"Chega de som ruim e casa sem graça! "
        f"Clique no link aqui na tela ou escaneie o código para garantir a sua antes que o estoque acabe!"
    )

def download_image(url, path):
    try:
         headers = {"User-Agent": "Mozilla/5.0"}
         res = requests.get(url, stream=True, timeout=15, headers=headers)
         if res.status_code == 200:
             with open(path, 'wb') as f:
                 for chunk in res.iter_content(1024): f.write(chunk)
             return True
    except: pass
    return False

def create_video_with_sales_pitch(
    image_paths, audio_path, qr_code_path, output_path,
    product_title, price_display, duration
):
    audio_clip = AudioFileClip(audio_path)
    final_duration = audio_clip.duration + 0.5

    if len(image_paths) == 1:
        image_paths = image_paths * 3
    elif len(image_paths) == 2:
        image_paths = image_paths + [image_paths[0]]

    time_per_image = final_duration / len(image_paths)
    
    clips = []
    bg = ColorClip(size=(1080, 1920), color=(15, 15, 15), duration=final_duration)
    clips.append(bg)

    texts = ["ACHADINHO\nAMAZON!", "SOM ABSURDO\nE GRAVES", "OFERTA\nLIMITADA!"]
    colors = ["yellow", "cyan", "red"]

    for i, img in enumerate(image_paths):
        start_time = i * time_per_image
        end_time = start_time + time_per_image if i < len(image_paths)-1 else final_duration
        clip_dur = end_time - start_time
        
        img_clip = ImageClip(img).resize(width=1080).set_position('center').set_start(start_time).set_duration(clip_dur).crossfadein(0.2)
        clips.append(img_clip)

        txt_bg = ColorClip(size=(900, 250), color=(0,0,0), duration=clip_dur).set_opacity(0.8).set_position(('center', 0.12), relative=True).set_start(start_time)
        txt = TextClip(texts[i % len(texts)], fontsize=90, color=colors[i % len(colors)], font='Impact', align='center').set_position(('center', 0.12), relative=True).set_start(start_time).set_duration(clip_dur)
        clips.append(txt_bg)
        clips.append(txt)

    half_time = final_duration * 0.55
    price_bg = ColorClip(size=(900, 180), color=(200, 0, 0), duration=final_duration - half_time).set_position(('center', 0.78), relative=True).set_start(half_time).crossfadein(0.5)
    price_text = TextClip(f"APENAS\n{price_display}", fontsize=80, color='white', font='Impact', align='center').set_position(('center', 0.78), relative=True).set_start(half_time).crossfadein(0.5)
    clips.append(price_bg)
    clips.append(price_text)

    qr_clip = ImageClip(qr_code_path).resize(0.35).set_position(('right', 'bottom')).set_start(0).set_duration(final_duration)
    clips.append(qr_clip)

    video = CompositeVideoClip(clips, size=(1080, 1920)).set_audio(audio_clip)
    video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")