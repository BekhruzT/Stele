import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple, Union


from core.types import (
    ConclusionBulletPoint, ConclusionSlide, Diagram, TextSlide,
    TextSlideElement, TextSlideElementType)
from core.log import \
    setup_logging
from core.helpers import \
    image_to_data_uri
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright
from pydantic import BaseModel
from core.context import APVideoContext as Context
from core.hash import hash_image_description
from core.clients.s3 import download, load_json_from_s3, upload_file_to_s3

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

def render_conclusion_slides_template(context: Context, conclusion_slide: ConclusionSlide) -> str:
    id = hash_image_description('\n'.join([point.text for point in conclusion_slide.bullet_points]))
    duration = conclusion_slide.end_time - conclusion_slide.start_time
    s3_video_path = context.media_path + f'ConclusionSlides/{id}.mp4'

    local_background_path = os.path.join(TMP, 'conclusion_background.png')
    download(conclusion_slide.background_src, local_background_path)
    conclusion_slide.background_src = image_to_data_uri(local_background_path)
    src = generate_video_asset_from_html('conclusion_slide.html', s3_video_path, {'slide': conclusion_slide.model_dump()}, duration=duration, id=id)

    return src

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




if __name__ == '__main__':
    from core.context import prep_content_gen_input

    setup_logging(level=logging.INFO)

    # context = prep_content_gen_input({
    #     "ExecutionInput": {
    #         "curriculum": "college_board",
    #         "course": "AP World History: Video Lessons",
    #         "grade": "Grade 11",
    #         "subject": "AP World History - v1",
    #         "category": "High School: AP World History: Modern"
    #     },
    #     "Input": {
    #         "unit": "World History",
    #         "chapter": "Networks of Exchange",
    #         "section": "Exchange in the Indian Ocean",
    #         "subsection": "Explain the effects of the growth of networks of exchange after 1200."
    #     }
    # })
    # context = Context(**context)
    # bullet_slide = ConclusionSlide(
    #     title="Economic Evolution Highlights",
    #     bullet_points=[
    #         ConclusionBulletPoint(text="Agricultural Innovations: Champa rice, Irrigation", start_time=477.303),
    #         ConclusionBulletPoint(text="Manufacturing Advances: Movable type, Porcelain, Textiles", start_time=496.053),
    #         ConclusionBulletPoint(text="Expanding Trade Networks: Maritime Silk Road, Magnetic compass", start_time=516.126),
    #         ConclusionBulletPoint(text="Economic Commercialization: Flying cash, Grand Canal, Urbanization", start_time=534.796),
    #         ConclusionBulletPoint(text="Peasant and Artisanal Labor: Peasants & Artisans", start_time=553.267),
    #         # BulletPoint(text="Trade Expansion: Routes & Cities", start_time=10.0)
    #     ],
    #     start_time=467.179,
    #     end_time =582.002
    # )
    # logger.info(render_conclusion_slides_template(context, bullet_slide))
    
    context = prep_content_gen_input({
        "ExecutionInput": {
            "curriculum": "college_board",
            "course": "AP World History: Video Lessons 2",
            "grade": "Grade 11",
            "subject": "AP World History - v0",
            "category": "High School: AP World History: Modern"
        },
        "Input": {
            "unit": "World History",
            "chapter": "The Global Tapestry",
            "section": "Developments in East Asia from c. 1200 to c. 1450",
            "subsection": "Explain the systems of government employed by Chinese dynasties and how they developed over time."
        }
    })
    context = Context(**context)
    # bullet_slide = ConclusionSlide(
    #     title="Economic Evolution Highlights",
    #     bullet_points=[
    #         ConclusionBulletPoint(text="Agricultural Innovations: Champa rice, Irrigation", start_time=477.303),
    #         ConclusionBulletPoint(text="Manufacturing Advances: Movable type, Porcelain, Textiles", start_time=496.053),
    #         ConclusionBulletPoint(text="Expanding Trade Networks: Maritime Silk Road, Magnetic compass", start_time=516.126),
    #         ConclusionBulletPoint(text="Economic Commercialization: Flying cash, Grand Canal, Urbanization", start_time=534.796),
    #         ConclusionBulletPoint(text="Peasant and Artisanal Labor: Peasants & Artisans", start_time=553.267),
    #         # BulletPoint(text="Trade Expansion: Routes & Cities", start_time=10.0)
    #     ],
    #     start_time=467.179,
    #     end_time =582.002
    # )
    # logger.info(render_conclusion_slides_template(context, bullet_slide))


    text_slide_data = {
      "title": "LBJ Takes Office",
      "start_index": 167,
      "end_index": 319,
      "start_time": 70.949,
      "end_time": 141.773,
      "elements": [
        {
          "type": "text",
          "content": "After the awful tragedy of President Kennedy's assassination, Lyndon Johnson became the president.",
          "phrase": "our nation reeled from the awful tragedy of President Kennedy's assassination. I stepped into the presidency",
          "start_index": 167,
          "start_time": 3.529,
          "start_duration": 7.617
        },
        {
          "type": "text",
          "content": "The next year, Lyndon Johnson sought the people's mandate and won a full term in 1964.",
          "phrase": "The next year, I sought the people's mandate and won a full term in 1964.",
          "start_index": 208,
          "start_time": 20.167,
          "start_duration": 4.459999999999994
        },
        {
          "type": "text",
          "content": "Lyndon Johnson's long service in Congress, coupled with strong Democratic majorities, helped him pass Kennedy's stalled bills.",
          "phrase": "My long service in Congress, coupled with strong Democratic majorities, helped me pass Kennedy's stalled bills",
          "start_index": 223,
          "start_time": 26.506,
          "start_duration": 6.339999999999989
        },
        {
          "type": "text",
          "content": "Johnson then launched his Great Society programs, which sought to uplift education and health services.",
          "phrase": "I then launched my Great Society programs, which sought to uplift education and health services",
          "start_index": 246,
          "start_time": 36.861000000000004,
          "start_duration": 5.887999999999991
        }
      ],
      "src": "college_board/AP US History: Video Lessons/AP US History - vUnit_8_new/media/90506313/TextSlides/f2eb617f.mov"
    }
    # logger.info("Rendering text slide template")
    # render_template('text_slide.html', text_slide_data, output_path='text-slide-output.html')
    # logger.info("Converting HTML to video")
    # convert_html_to_video('text-slide-output.html', 'f2eb617f.mov', text_slide_data['end_time'] - text_slide_data['start_time'])
    # logger.info('Done! Rendered text slide')

    avatar_intro_data = {
      "start_time": 121.49300000000001,
      "end_time": 135.184,
      "avatar_name": "Grace Lee Boggs",
      "description": "Asian American activist witnessing immigrant neighborhood transformations",
      "src": "college_board/AP US History: Video Lessons/AP US History - vUnit_8_new/media/2fd17a43/Avatar/Introduction/cbe26e3f.mov"
    }
    # logger.info("Rendering avatar intro template")
    # render_template('avatar_introduction.html', {'avatar_intro': avatar_intro_data, 'duration': avatar_intro_data['end_time'] - avatar_intro_data['start_time']}, output_path='avatar-intro-output.html')
    # logger.info("Converting HTML to video")
    # convert_html_to_video('avatar-intro-output.html', 'cbe26e3f.mov', avatar_intro_data['end_time'] - avatar_intro_data['start_time'])
    # logger.info('Done! Rendered avatar intro')

    # Sample mind map data
    mind_map_data = {
        "start_phrase": "We established the Department of Housing",
        "start_time": 460.562,
        "root": {
          "title": "Housing and Social Welfare",
          "icon": "house-user"
        },
        "categories": [
          {
            "title": {
              "text": "Department of Housing and Urban Development",
              "icon": "building",
              "phrase": "We established the Department of Housing and Urban Development in 1965",
              "start_time": 0.0
            },
            "points": [
              {
                "text": "Established in 1965",
                "icon": "",
                "phrase": "We established the Department of Housing and Urban Development in 1965",
                "start_time": 0.0
              },
              {
                "text": "Part of Great Society agenda",
                "icon": "",
                "phrase": "to move ahead with my Great Society agenda",
                "start_time": 4.122000000000014
              },
              {
                "text": "Oversaw federal housing efforts",
                "icon": "",
                "phrase": "That new department oversaw federal housing efforts",
                "start_time": 13.676999999999964
              }
            ]
          },
          {
            "title": {
              "text": "Healthcare Programs",
              "icon": "hospital",
              "phrase": "We also introduced social welfare programs such as Medicare and Medicaid",
              "start_time": 22.257000000000005
            },
            "points": [
              {
                "text": "Enduring social welfare initiatives",
                "icon": "",
                "phrase": "We also introduced social welfare programs",
                "start_time": 22.257000000000005
              },
              {
                "text": "Medicare and Medicaid introduced",
                "icon": "",
                "phrase": "Medicare and Medicaid",
                "start_time": 25.555
              },
              {
                "text": "Important safety net for Americans",
                "icon": "",
                "phrase": "which remain an important safety net for Americans",
                "start_time": 27.841000000000008
              }
            ]
          },
          {
            "title": {
              "text": "Mid-1960s Liberalism",
              "icon": "landmark",
              "phrase": "These programs illustrated mid-1960s liberalism",
              "start_time": 32.65899999999999
            },
            "points": [
              {
                "text": "Anti-communism abroad",
                "icon": "",
                "phrase": "based on anti-communism abroad",
                "start_time": 36.87399999999997
              },
              {
                "text": "Federal power for social problems",
                "icon": "",
                "phrase": "and a strong belief in using federal power to solve major social problems",
                "start_time": 38.986999999999966
              },
              {
                "text": "Reached high point of influence",
                "icon": "",
                "phrase": "which by then had reached its high point of political influence",
                "start_time": 43.64299999999997
              }
            ]
          }
        ],
        "is_section": False
      }
    # logger.info("Rendering mind map template")
    # render_template('diagrams/mind_map.html', mind_map_data, output_path='mind-map-output.html')
    # logger.info("Converting HTML to video")
    # convert_html_to_video('mind-map-output.html', '3b3d9a18.mov', 75.678)
    # logger.info('Done! Rendered mind map')
    

    # Sample venn diagram data
    venn_data = {
        "root": {
            "title": "Neo-Confucianism",
            "subtitle": "Personal Growth Learning"
        },
        "circles": [
            {
                "name": {
                    "text": "Buddhism",
                    "start_time": 0.5
                },
                "points": [
                    {
                        "text": "Self-awareness",
                        "start_time": 1.0
                    },
                    {
                        "text": "Meditation",
                        "start_time": 1.5
                    },
                    {
                        "text": "Self-development",
                        "start_time": 2.0
                    }
                ]
            },
            {
                "name": {
                    "text": "Daoism",
                    "start_time": 0.5
                },
                "points": [
                    {
                        "text": "Natural Order",
                        "start_time": 1.0
                    },
                    {
                        "text": "Balance with Nature",
                        "start_time": 1.5
                    }
                ]
            },
            {
                "name": {
                    "text": "Confucianism",
                    "start_time": 0.5
                },
                "points": [
                    {
                        "text": "Moral Integrity",
                        "start_time": 1.0
                    },
                    {
                        "text": "Social Harmony",
                        "start_time": 1.5
                    }
                ]
            }
        ],
        "intersection": {
            "text": "Lorem Ipsum",
            "start_time": 2.5
        }
    }
    # logger.info("Rendering venn diagram template")
    # render_template('diagrams/venn_diagram.html', venn_data, output_path='venn-output.html')
    # logger.info("Converting HTML to video")
    # convert_html_to_video('venn-output.html', 'venn-output.mp4', 10)
    # logger.info('Done! Rendered venn diagram')

    # Sample tree diagram data

    tree_data = {
        "title": "Tree Diagram",
        "tree": {
            "title": "UN Decision-Making",
            "icon": "globe",
            "is_root": True,
            "start_time": 0,
            "children": [
                {
                    "title": "Security Council",
                    "icon": "shield-alt",
                    "start_time": 0,
                    "children": [
                        {
                            "title": "Council Composition",
                            "description": "five permanent members (United States, United Kingdom, France, Russia, China), ten rotating non-permanent members",
                            "icon": "users",
                            "start_time": 0,
                        },
                        {
                            "title": "Veto Power",
                            "description": "reflecting post-World War II power dynamics",
                            "icon": "ban",
                            "start_time": 0,
                        },
                        {
                            "title": "Intervention Powers",
                            "description": "peacekeepers, economic sanctions",
                            "icon": "gavel",
                            "start_time": 0,
                        }
                    ]
                },
                {
                    "title": "General Assembly",
                    "icon": "landmark",
                    "start_time": 0,
                    "children": [
                        {
                            "title": "Equal Representation",
                            "description": "all nations participate",
                            "icon": "users",
                            "start_time": 0,
                        },
                        {
                            "title": "Limited Authority",
                            "description": "non-binding resolutions",
                            "icon": "file",
                            "start_time": 0,
                        }
                    ]
                }
            ]
        }
    }
    # logger.info("Rendering tree diagram template")
    # render_template('diagrams/tree.html', tree_data, output_path='tree-output.html')
    # logger.info("Converting HTML to video")
    # convert_html_to_video('tree-output.html', 'tree-output.mp4', 10)
    # logger.info('Done! Rendered tree diagram')

    # Sample lesson organizer data
    lesson_organizer_data = {
        "start_phrase": "In this first section, we'll explore",
        "start_time": 33.343,
        "root": {
          "title": "Agricultural Innovations",
          "icon": "tractor"
        },
        "categories": [
          {
            "title": {
              "text": "New Farming Methods",
              "icon": "seedling",
              "phrase": "new farming methods known as the Green Revolution",
              "start_time": 2
            },
            "points": []
          },
          {
            "title": {
              "text": "Food Production And Society",
              "icon": "wheat-awn",
              "phrase": "affecting both food production and society as a whole",
              "start_time": 4
            },
            "points": []
          }
        ],
        "is_section": True
      }
    # logger.info("Rendering lesson organizer template")
    # render_template('diagrams/lesson_organizer.html', lesson_organizer_data, output_path='lesson-organizer-output.html')
    # logger.info("Converting HTML to video")
    # convert_html_to_video('lesson-organizer-output.html', 'lesson-organizer-output.mp4', 10)
    # logger.info('Done! Rendered lesson organizer')
