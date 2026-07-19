import os
import subprocess
import requests
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, ImageClip, TextClip, ColorClip
import moviepy.video.fx.all as vfx

subprocess.run(["pip", "install", "-q", "yt-dlp"])
import yt_dlp

def generate_aggressive_script(product_title, market):
    # Quebra o título para usar apenas a palavra principal
    short_title = product_title.split('|')[0].split('-')[0].split(',')[0].strip()
    
    # Textos criados para durar entre 20 a 40 segundos e reter a atenção
    if market == "BR":
        return (
            f"Se você tem amor ao seu dinheiro, você precisa ver isso agora! "
            f"Esse é o famoso {short_title} que está enlouquecendo todo mundo na internet. "
            f"A qualidade desse produto ao vivo é surreal, ele resolve aquele problema chato do dia a dia em minutos, sem você fazer esforço nenhum. "
            f"A Amazon liberou um lote com desconto escondido e o link está aqui no código na tela ou na bio. "
            f"E não esqueça de fazer parte da nossa comunidade para mais produtos todos os dias!"
        )
    else:
        return (
            f"If you value your hard-earned money, you need to see this right now! "
            f"This is the famous {short_title} that is breaking the internet. "
            f"The quality of this product in person is insane, it solves that annoying daily struggle in minutes with zero effort. "
            f"Amazon just dropped a hidden discount batch and the link is on the screen or in the bio. "
            f"Don't forget to join our community for daily product finds!"
        )

def create_viral_video(job_id, audio_path, qr_code_path, output_path, product_title, market):
    audio_clip = AudioFileClip(audio_path)
    final_duration = audio_clip.duration
    short_title = product_title.split('|')[0].split('-')[0].split(',')[0].strip()
    yt_vid_path = f"/atlas/storage/tmp/yt_{job_id}.mp4"
    
    # 1. Busca o vídeo no YouTube (prioriza Shorts)
    search_query = f"ytsearch1:{short_title} review shorts tiktok"
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': yt_vid_path,
        'quiet': True,
        'match_filter': yt_dlp.utils.match_filter_func('duration < 180')
    }
    
    video_clip = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(search_query, download=True)
        
        raw_video = VideoFileClip(yt_vid_path)
        
        # 2. RETIRA O SOM ORIGINAL DO VÍDEO DO YOUTUBE
        try: raw_video = raw_video.without_audio()
        except: pass
        
        # 3. Formata para Vertical (9:16) preenchendo a tela toda
        w, h = raw_video.size
        target_ratio = 1080 / 1920
        if w/h > target_ratio:
            new_w = int(h * target_ratio)
            raw_video = vfx.crop(raw_video, x_center=w/2, y_center=h/2, width=new_w, height=h)
        raw_video = raw_video.resize(height=1920, width=1080)
        
        # Sincroniza a duração do vídeo com o tamanho exato da locução (15 a 60s)
        if raw_video.duration < final_duration:
            raw_video = vfx.loop(raw_video, duration=final_duration)
        else:
            raw_video = raw_video.subclip(0, final_duration)
            
        video_clip = raw_video
    except Exception as e:
        print(f"Erro YT: {e}. Procurando vídeo genérico de fundo...")
        # Fallback de segurança em último caso
        video_clip = ColorClip(size=(1080, 1920), color=(15, 15, 15), duration=final_duration)

    # 4. Textos de Retenção Visual
    t_topo = "OLHA ISSO!" if market == "BR" else "LOOK AT THIS!"
    t_baixo = "LINK NA BIO" if market == "BR" else "LINK IN BIO"
    
    txt_topo = TextClip(t_topo, fontsize=120, color='yellow', font='Impact', stroke_color='black', stroke_width=4, align='center').set_position(('center', 0.1), relative=True).set_duration(final_duration)
    txt_baixo = TextClip(t_baixo, fontsize=90, color='white', bg_color='red', font='Impact', align='center').set_position(('center', 0.65), relative=True).set_start(2).set_duration(final_duration - 2)

    # QR Code do produto
    qr_clip = ImageClip(qr_code_path).resize(0.35).set_position(('center', 0.75), relative=True).set_start(0).set_duration(final_duration)
    
    # Junta tudo: Vídeo mudo do YouTube + IA Voiceover + Textos + QR Code
    final_video = CompositeVideoClip([video_clip, txt_topo, txt_baixo, qr_clip], size=(1080, 1920)).set_audio(audio_clip)
    final_video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac")