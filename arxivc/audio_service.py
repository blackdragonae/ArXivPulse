import os
import subprocess
import uuid

def stream_speech(text: str, voice_id: str = None) -> str:
    """
    Generates audio using Mac's built-in 'say' command.
    Returns the path to the generated audio file.
    """
    # Create a unique temp file
    filename = f"podcast_{uuid.uuid4().hex}.m4a"
    filepath = os.path.join("downloads", filename)
    
    # Ensure dir exists
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
        
    try:
        # Use 'say' command. 
        # -o defines output file. 
        # --data-format=LEF32@8000 is not needed for m4a usually.
        # We pass text via stdin to avoid command line length limits.
        
        process = subprocess.Popen(
            ['say', '-o', filepath, '--data-format=aac', '--file-format=m4af'], 
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        process.communicate(input=text.encode('utf-8'))
        
        if process.returncode != 0:
            print("Error running 'say' command.")
            return None
            
        return filepath
    except Exception as e:
        print(f"Exception generating audio: {e}")
        return None

def generate_conversation_audio(script: list[dict]) -> str:
    """
    Generates a podcast audio file from a script using multi-voice TTS.
    Stitches WAV files together.
    """
    import wave
    
    temp_files = []
    
    # 1. Generate Segments
    if not os.path.exists("downloads"):
         os.makedirs("downloads")

    for i, line in enumerate(script):
        role = line['role']
        text = line['text']
        
        # Voice Selection (Mac/Standard)
        voice = "Alex" if role == "Host" else "Samantha" 
        
        # Generate WAV segment (Int16, 24kHz for speech is enough, but 44.1k is safer)
        seg_name = f"seg_{i}_{uuid.uuid4().hex}.wav"
        seg_path = os.path.join("downloads", seg_name)
        
        try:
             # data-format=LEI16@22050 (Little Endian Integer 16-bit at 22.05kHz)
             subprocess.run(
                ['say', '-v', voice, '-o', seg_path, '--data-format=LEI16@22050'], 
                input=text.encode('utf-8'),
                check=True,
                stderr=subprocess.DEVNULL
            )
             temp_files.append(seg_path)
        except Exception as e:
            print(f"Error generating segment {i}: {e}")
            
    if not temp_files:
        return None
        
    # 2. Stitch Files
    output_filename = f"podcast_duo_{uuid.uuid4().hex}.wav"
    output_path = os.path.join("downloads", output_filename)
    
    try:
        data = []
        params = None
        
        for tf in temp_files:
            with wave.open(tf, 'rb') as w:
                if not params:
                    params = w.getparams()
                data.append(w.readframes(w.getnframes()))
                
        with wave.open(output_path, 'wb') as outfile:
            outfile.setparams(params)
            for d in data:
                outfile.writeframes(d)
                
        # Cleanup temps
        for tf in temp_files:
            if os.path.exists(tf):
                os.remove(tf)
                
        return output_path
        
    except Exception as stitch_err:
        print(f"Error stitching audio: {stitch_err}")
        return None
