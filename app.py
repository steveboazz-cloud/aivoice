import gradio as gr
import edge_tts
import asyncio
import textwrap
import datetime
import os
import re
from mutagen.mp3 import MP3
from pydub import AudioSegment

# --- သက်တမ်းသတ်မှတ်ချက် ---
EXPIRY_DATE = datetime.date(2026, 9, 7) 

def is_expired(): 
    return datetime.date.today() > EXPIRY_DATE 

def check_auth(u, p): 
    if is_expired(): return False 
    return u == "admin" and p == "122412" 

# SRT အချိန် Format ချခြင်း
def format_time(seconds): 
    seconds = max(0, seconds) 
    td = datetime.timedelta(seconds=seconds) 
    return f"{int(td.total_seconds()//3600):02}:{int((td.total_seconds()%3600)//60):02}:{int(td.total_seconds()%60):02},{int(td.microseconds/1000):03}" 

# --- 🎙️ အသံ (၆) မျိုး၏ အခြေခံ Preset များ ---
VOICE_PRESETS = {
    "ယောကျာ်းလေးအသံ":    {"base": "my-MM-ThihaNeural", "rate": 0,   "pitch": 0},
    "မိန်းကလေးအသံ":      {"base": "my-MM-NilarNeural", "rate": 0,   "pitch": 0},
    "ကလေးသံ(မ)":        {"base": "my-MM-NilarNeural", "rate": 10,  "pitch": 15},  
    "ကလေးသံ(ကျား)":      {"base": "my-MM-ThihaNeural", "rate": 12,  "pitch": 15},
    "နိုင်လူသံ(ကျား)":     {"base": "my-MM-ThihaNeural", "rate": -5,  "pitch": -8}, 
    "မရင်ရွှေသံ(မ)":       {"base": "my-MM-NilarNeural", "rate": -8,  "pitch": -6}, 
}

async def process_line_audio(clean_text, voice_name, style_name, user_rate, user_pitch, idx):
    preset = VOICE_PRESETS.get(voice_name, VOICE_PRESETS["ယောကျာ်းလေးအသံ"])
    base_voice = preset["base"]
    
    v_rate = preset["rate"]
    v_pitch = preset["pitch"]
    
    styles = {"သာမန်": (0, 0), "ဇာတ်လမ်းပြောသူ": (-6, -4), "ကြေညာသူ": (10, 5), "ကလေးအသံ": (4, 15)} 
    s_rate, s_pitch = styles.get(style_name, (0, 0))
    
    final_rate = v_rate + s_rate + user_rate
    final_pitch = v_pitch + s_pitch + user_pitch
    
    line_fp = f"part_{idx}.mp3"
    
    if not clean_text.strip():
        AudioSegment.silent(duration=500).export(line_fp, format="mp3")
        return line_fp, ""
        
    rate_str = f"{max(min(final_rate, 50), -50):+d}%"
    pitch_str = f"{max(min(final_pitch, 50), -50):+d}Hz"
    
    communicate = edge_tts.Communicate(clean_text, base_voice, rate=rate_str, pitch=pitch_str)
    await communicate.save(line_fp)
    return line_fp, clean_text

async def generate_audio(text, main_voice, style, rate, pitch, delay, multiplier): 
    audio_file = "output.mp3" 
    srt_file = "subtitles.srt" 
    
    lines = text.strip().split('\n')
    tag_to_voice = {
        "[V1]": "ယောကျာ်းလေးအသံ", "[V2]": "မိန်းကလေးအသံ",
        "[V3]": "ကလေးသံ(မ)", "[V4]": "ကလေးသံ(ကျား)",
        "[V5]": "နိုင်လူသံ(ကျား)", "[V6]": "မရင်ရွှေသံ(မ)",
    }
    
    current_voice = main_voice
    temp_files = []
    srt_lines = []
    
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
            
        clean_line = line
        
        # Pause Tags
        pause_match = re.search(r"\[pause=(\d+(\.\d+)?)\]", clean_line)
        short_pause = "[short pause]" in clean_line
        
        if pause_match:
            seconds = float(pause_match.group(1))
            clean_line = clean_line.replace(pause_match.group(0), "").strip()
            temp_fp = f"part_{idx}_pause.mp3"
            AudioSegment.silent(duration=int(seconds * 1000)).export(temp_fp, format="mp3")
            temp_files.append(temp_fp)
            if clean_line: srt_lines.append(f"(ခေတ္တရပ်နားခြင်း {seconds} စက္ကန့်)")
            
        elif short_pause:
            clean_line = clean_line.replace("[short pause]", "").strip()
            temp_fp = f"part_{idx}_pause.mp3"
            AudioSegment.silent(duration=500).export(temp_fp, format="mp3")
            temp_files.append(temp_fp)
            if clean_line: srt_lines.append("(ခဏဖြတ်)")

        # Voice Tags
        matched_voice_tag = None
        for tag in tag_to_voice.keys():
            if tag in clean_line:
                matched_voice_tag = tag
                current_voice = tag_to_voice[tag]
                break
                
        if matched_voice_tag:
            clean_line = clean_line.replace(matched_voice_tag, "").strip()
            
        if clean_line.strip():
            fp, final_srt_text = await process_line_audio(clean_line, current_voice, style, rate, pitch, idx)
            temp_files.append(fp)
            if final_srt_text:
                srt_lines.append(final_srt_text)

    # Audio ပြန်ပေါင်းခြင်း
    if temp_files:
        combined = AudioSegment.empty()
        for file in temp_files:
            if os.path.exists(file):
                combined += AudioSegment.from_mp3(file)
                os.remove(file)
        combined.export(audio_file, format="mp3")
    else:
        AudioSegment.silent(duration=1000).export(audio_file, format="mp3")

    # SRT တည်ဆောက်ခြင်း
    try:
        audio = MP3(audio_file) 
        total_duration = audio.info.length 
    except Exception:
        total_duration = len(text) * 0.2  
        
    if not srt_lines: srt_lines = ["..."]
    duration_per_line = (total_duration / len(srt_lines)) * multiplier 
    with open(srt_file, "w", encoding="utf-8-sig") as f: 
        for i, line in enumerate(srt_lines, 1): 
            start = ((i-1) * duration_per_line) + delay 
            end = (i * duration_per_line) + delay 
            f.write(f"{i}\n{format_time(start)} --> {format_time(end)}\n{line}\n\n") 
            
    return audio_file, srt_file 

# --- 💡 Gradio UI Layout ဗားရှင်းသစ် (အောက်သို့ စီချထားသော ပုံစံ) ---
expiry_str = EXPIRY_DATE.strftime("%Y ခုနှစ်၊ %m လ၊ %d ရက်")
with gr.Blocks(theme=gr.themes.Ocean()) as demo:
    gr.Markdown(f"<div style='background-color: #e6f7ff; padding: 15px; border-radius: 8px;'><b>သက်တမ်း -</b> {expiry_str} အထိ</div>")

    if is_expired(): 
        gr.Markdown("# ⚠️ သက်တမ်းကုန်ဆုံးသွားပါပြီ!") 
    else: 
        gr.Markdown("# 🎙️ Myanmar AI Studio") 
        
        # ၁။ စာသားထည့်ရန်နေရာ
        with gr.Row(): 
            placeholder_text = "[V1] မင်္ဂလာပါဗျ\n[V2] မင်္ဂလာပါရှင့်\n[V3] အဆင်ပြေပါစေ"
            user_text = gr.Textbox(label="စာသားထည့်ရန်", lines=10, placeholder=placeholder_text) 
            
        # ၂။ Generate ခလုတ်ကြီး
        with gr.Row():
            gen_btn = gr.Button("🎬 Generate Audio & SRT", variant="primary") 
            
        # ၃။ ရလဒ်ထွက်မည့်နေရာ (Audio ရော SRT ပါ ဘေးချင်းယှဉ်မြင်ရမည်)
        with gr.Row(): 
            audio_out = gr.Audio(label="ရလဒ် အသံဖိုင်") 
            srt_out = gr.File(label="SRT ဖိုင်") 
            
        gr.Markdown("---")
        
        # ၄။ အသံဒီဇိုင်း ဆက်တင်အပိုင်း (အောက်သို့ ရွှေ့ထားပါသည်)
        with gr.Group():
            gr.Markdown("### 🎤 အသံဒီဇိုင်း")
            with gr.Row():
                voice = gr.Dropdown(choices=list(VOICE_PRESETS.keys()), label="အခြေခံအသံရွေးရန်", value="ယောကျာ်းလေးအသံ") 
                style = gr.Radio(["သာမန်", "ဇာတ်လမ်းပြောသူ", "ကြေညာသူ", "ကလေးအသံ"], label="Style", value="သာမန်") 
                
        # ၅။ အဆင့်မြင့်ချိန်ညှိမှု ဆက်တင်အပိုင်း (အောက်ဆုံးသို့ ရွှေ့ထားပါသည်)
        with gr.Group():
            gr.Markdown("### 🎚️ အဆင့်မြင့်ချိန်ညှိမှု")
            with gr.Row(): 
                rate = gr.Slider(-50, 50, 0, label="Manual Rate") 
                pitch = gr.Slider(-50, 50, 0, label="Manual Pitch (Hz)") 
            with gr.Row():
                delay = gr.Slider(0, 2.0, 0.3, label="Delay (စက္ကန့်)") 
                multiplier = gr.Slider(0.5, 2.0, 1.1, label="Duration Multiplier") 
            
        gen_btn.click(generate_audio, inputs=[user_text, voice, style, rate, pitch, delay, multiplier], outputs=[audio_out, srt_out]) 

demo.launch(auth=check_auth)