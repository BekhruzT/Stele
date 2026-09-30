import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from typing import Optional


from core.types import (
    Diagram, TextSlide)
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright
from core.context import Context
from core.hash import hash_image_description
from core.clients.s3 import upload_file_to_s3

logger = logging.getLogger(__name__)

# Was a hardcoded '/tmp', which does not exist on Windows. gettempdir() honours TMPDIR/TEMP and
# falls back to /tmp on posix, so the Lambda behaviour is unchanged.
TMP = tempfile.gettempdir()

TEMPLATES = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'templates'))

# A rendered page has to sit inside TEMPLATES for its relative links to components/ to
# resolve, which puts scratch files in a source directory. The prefix keeps them from ever
# colliding with a real template, and staged_page() refuses to overwrite one regardless --
# without that, rendering an asset whose id happened to be 'text_slide' would silently
# destroy text_slide.html.
SCRATCH = '_render_'


@contextmanager
def staged_page(template_file: str, data: dict, id: str):
    """Render a template to a scratch page beside it, and remove the page afterwards."""
    path = os.path.join(TEMPLATES, f'{SCRATCH}{id}.html')
    if os.path.exists(path):
        raise FileExistsError(f"refusing to overwrite {path}")
    render_template(template_file, data, output_path=path)
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.remove(path)


def render_template(html_file, data, output_path=None):
    env = Environment(loader=FileSystemLoader(TEMPLATES))
    template = env.get_template(html_file)
    rendered_html = template.render(**data)
    if output_path is not None:
        # utf-8 for the same reason prompts.txt needs it: the slide text is model output and
        # arrives full of curly quotes and dashes that cp1252 cannot encode.
        with open(output_path, 'w', encoding='utf-8') as file:
            file.write(rendered_html)

    return rendered_html


async def html_to_mov(html_file: str, output_file: str, duration: float) -> None:
    id = os.path.basename(output_file).split('.')[0]
    frame_dir = os.path.join(TMP, 'video_frames', id)
    os.makedirs(frame_dir, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        # Set the background to be transparent for MOV
        await page.evaluate("""
        () => {
            document.body.style.background = 'transparent';
        }
        """)

        # Load the HTML file
        await page.goto(f'file://{os.path.abspath(html_file)}')

        # Prepare animations control and override time functions
        await page.evaluate("""
            () => {
                // Pause all animations
                window.animations = document.getAnimations();
                window.animations.forEach(animation => animation.pause());

                // Override Date.now() and performance.now()
                window.customTime = 0;
                Date.now = () => window.customTime;
                performance.now = () => window.customTime;
            }
        """)

        frames = int(duration * 30)  # Assuming 30 fps
        frame_duration = duration / frames  # Duration per frame in seconds

        for i in range(frames):
            elapsed_time = i * frame_duration * 1000  # in milliseconds

            # Advance animations and update custom time
            await page.evaluate("""
                elapsedTime => {
                    window.customTime = elapsedTime;
                    window.animations.forEach(animation => {
                        animation.currentTime = elapsedTime;
                    });
                }
            """, elapsed_time)

            frame_path = os.path.join(frame_dir, f'frame_{i:03d}.png')
            await page.screenshot(path=frame_path, omit_background=True)

        await context.close()
        await browser.close()

    # For MOV with alpha channel
    command = [
        'ffmpeg',
        '-framerate', '30',
        '-i', os.path.join(frame_dir, 'frame_%03d.png'),
        '-c:v', 'qtrle',
        '-loglevel', 'error',
        '-y',
        output_file
    ]

    try:
        subprocess.run(command, check=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        logger.error(f"An error occurred: {e.stderr.decode()}")

    # Clean up temporary files
    shutil.rmtree(frame_dir)

async def html_to_mp4(html_file: str, output_file: str, duration: float) -> None:
    id = os.path.basename(output_file).split('.')[0]
    video_dir = os.path.join(TMP, 'video_frames', id)
    os.makedirs(video_dir, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        # Enable video recording
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=video_dir,
            record_video_size={"width": 1280, "height": 720},
            # reduced_motion="reduce"  # Ensure animations are not sped up
        )
        page = await context.new_page()

        # Load the HTML file
        await page.goto(f'file://{os.path.abspath(html_file)}')

        # Wait for the total duration of the animation
        await page.wait_for_timeout(duration * 1000)  # Convert duration to milliseconds

        await context.close()
        await browser.close()

    # Find the recorded video file
    video_file: Optional[str] = None
    for root, dirs, files in os.walk(video_dir):
        for file in files:
            if file.endswith('.webm'):
                video_file = os.path.join(root, file)
                break

    if not video_file:
        raise FileNotFoundError("Video file not found.")

    # Convert WebM to MP4
    command = [
        'ffmpeg',
        '-ss', '0.25', 
        '-i', video_file,
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-loglevel', 'error',
        '-y', 
        output_file
    ]

    try:
        subprocess.run(command, check=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        logger.error(f"An error occurred: {e.stderr.decode()}")

    # Clean up the recorded video files
    shutil.rmtree(video_dir)

# Usage examples:
def convert_html_to_video(html_path: str, video_path: str, duration: float = 2):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if video_path[-3:] == 'mp4':
            loop.run_until_complete(html_to_mp4(html_path, video_path, duration))
        elif video_path[-3:] == 'mov':
            loop.run_until_complete(html_to_mov(html_path, video_path, duration))
    finally:
        loop.close()


def render_text_slide_template(context: Context, text_slide: TextSlide) -> str:
    id = text_slide.src.split('/TextSlides/')[1][:-4] if text_slide.src else hash_image_description(json.dumps(text_slide.model_dump()))

    duration = text_slide.end_time - text_slide.start_time
    s3_video_path = context.media_path + f'TextSlides/{id}.mov'
    src = generate_video_asset_from_html('text_slide.html', s3_video_path, text_slide.model_dump(exclude_none=True), duration=duration, id=id)
    return src

def render_diagram_template(context: Context, diagram: Diagram) -> str:
    id = diagram.src.split('/Diagrams/')[1][:-4] if diagram.src else hash_image_description(json.dumps(diagram.data.model_dump()))
    duration = diagram.end_time - diagram.start_time
    s3_video_path = diagram.src  if diagram.src else context.media_path + f'Diagrams/{id}.mov'
    if diagram.type.value == 'tree':
        s3_video_path = s3_video_path.replace('.mov', '.mp4')
    src = generate_video_asset_from_html(f'diagrams/{diagram.type.value}.html', s3_video_path, diagram.data.model_dump(exclude_none=True), duration=duration, id=id)
    return src
                               
def generate_video_asset_from_html(template_file: str, s3_video_path: str, data: dict, duration: float=2, id: Optional[str] = None):
    id = str(uuid.uuid4()) if id is None else id
    video_path = os.path.join(TMP, f'{id}.{s3_video_path[-3:]}')

    # The page used to be written to './{id}.html', which depended on the process running from
    # the package root for its asset links to resolve. Nothing guarantees that.
    with staged_page(template_file, data, id) as html_path:
        convert_html_to_video(html_path, video_path, duration)
        upload_file_to_s3(video_path, s3_video_path)

    return s3_video_path
