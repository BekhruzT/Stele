import json
import logging
import os
import re
import subprocess
import time
import traceback
from typing import Dict, List, Optional

from core.types import (
    AudioClip, AvatarClip, AvatarIntroduction, ClipTypes, ConclusionSlide,
    Diagram, DiagramType, ImageClip, LayerName, LessonVideo, MediaClip,
    OverlaysData, TextSlide, TitleOverlay, TitleOverlayType, TranscriptOutput,
    TranscriptTiming, VideoClip)
from core.media.clip_timings import (
    identify_video_split_indexes, reset_timings)
from core.log import (
    setup_logging, with_logging_context)
from core.helpers import (
    exception_handler, print_json, sanitize_path, save_video)
from core.stage_constants import \
    get_sheet_info_by_subject
from core.media.thumbnails import \
    get_thumbnails
from core.media.lesson_report import \
    get_lesson_report
from core.clients.sheets import (
    append_row_to_sheet, does_gdrive_file_exist, get_sheet_row_count,
    get_worksheet_id, merge_cells, set_file_public, upload_s3_file_to_gdrive)
from core.clients.shotstack import \
    ShotstackClient
from core.clients.images import save_image
from shotstack_sdk.model.audio_asset import AudioAsset
from shotstack_sdk.model.clip import Clip
from shotstack_sdk.model.edit import Edit
from shotstack_sdk.model.image_asset import ImageAsset
from shotstack_sdk.model.offset import Offset
from shotstack_sdk.model.output import Output
from shotstack_sdk.model.timeline import Timeline
from shotstack_sdk.model.title_asset import TitleAsset
from shotstack_sdk.model.track import Track
from shotstack_sdk.model.transition import Transition
from shotstack_sdk.model.video_asset import VideoAsset
from core.context import APVideoContext as Context
from core.clients.s3 import (copy_s3_object, create_presigned_url, does_file_exist,
                      load_json_from_s3, upload_file_to_s3)
from core.clients.speech import create_subtitles_file

logger = logging.getLogger(__name__)

S3_VIEWER_BUCKET = os.getenv('S3_BUCKET_UI')

def split_lesson_video(video_path: str, splits: Dict[str, float], key: str) -> Dict[str, str]:
    start_time = 0
    split_videos = {}
    for ii, (name, end_time,) in enumerate(splits.items()):
        duration = end_time - start_time
        output_file = f"/tmp/{key}_{sanitize_path(name).replace('/', '_')}.mp4"
        subprocess.run([
            "ffmpeg",
            "-loglevel", "error",
            "-y",
            "-i", video_path,
            "-ss", str(start_time),
            "-t", str(duration),
            "-c", "copy",
            output_file
        ])
        start_time = end_time
        split_videos[name] = output_file

    return split_videos


def generate_audio_tracks(audio_list: List[AudioClip]) -> List[Track]:
    """
    Generate audio tracks from the list of audio clips
    """
    audio_tracks = []
    for audio in audio_list:
        audio_asset = AudioAsset(
            src=audio.src,
            # Note: we currently hardcode volume to 1
            volume=1.0
        )
        print(audio.speaker, audio_asset.volume, 'Audio')

        clip = Clip(asset=audio_asset, start=audio.start_time, length=audio.end_time - audio.start_time)
        if not audio_tracks:
            audio_tracks.append(Track(clips=[]))

        if audio_tracks[-1].clips:
            # If the audio clip overlaps with the previous audio clip, create a new track
            if audio.start_time < audio_tracks[-1].clips[-1].start + audio_tracks[-1].clips[-1].length:
                audio_tracks.append(Track(clips=[]))
        audio_tracks[-1].clips.append(clip)
    return audio_tracks


def generate_mediaclip_tracks(mediaclip_list: List[MediaClip]) -> List[Track]:
    """
    Generate media clip tracks from the list of media clips
    """
    mediaclip_tracks = []
    needs_transition = False
    for idx, mediaclip in enumerate(mediaclip_list):
        # TODO: Currently we only support video and image clips
        if mediaclip.type != ClipTypes.VIDEO.value and mediaclip.type != ClipTypes.IMAGE.value:
            logger.info(f'mediaclip type {mediaclip.type} is not supported, continue')
            continue

        # TODO: for image clips we should support scroll movements

        transition = Transition()
        if needs_transition:
            # TODO: We need to decide what kind of transition to apply
            # transition = Transition(
            #     _in= 'carouselRightFast'
            # )
            needs_transition = False

        clip_length = mediaclip.end_time - mediaclip.start_time

        if mediaclip.type == ClipTypes.VIDEO.value:
            asset = VideoAsset(
                src=mediaclip.contents.src,  # type: ignore
                volume=0.0,
            )
        elif mediaclip.type == ClipTypes.IMAGE.value:
            asset = ImageAsset(
                src=mediaclip.contents.src,  # type: ignore
            )

        # Check if there is an immediate mediaclip after the current mediaclip
        # If yes extend the length of the current mediaclip by 0.2 s and add transition to the next mediaclip
        if idx < len(mediaclip_list) - 1:
            next_mediaclip = mediaclip_list[idx + 1]
            if next_mediaclip.start_time - mediaclip.end_time < 0.2:
                if next_mediaclip.type == ClipTypes.IMAGE.value:
                    logger.info(f"Skipping transition on a clip preceding an IMAGE at: {next_mediaclip.start_time}")
                else:
                    clip_length += 0.2
                    needs_transition = True

        clip = Clip(
            asset=asset,
            start=mediaclip.start_time,
            length=clip_length,
            transition=transition,
            fit='contain',
            # **{'effect': 'slideLeft'} if mediaclip.type == ClipTypes.IMAGE.value else {}
        )

        if not mediaclip_tracks:
            mediaclip_tracks.append(Track(clips=[]))

        if mediaclip_tracks[-1].clips:
            # If the mediaclip overlaps with the previous mediaclip, create a new track
            if mediaclip.start_time < mediaclip_tracks[-1].clips[-1].start + mediaclip_tracks[-1].clips[-1].length:
                mediaclip_tracks.append(Track(clips=[]))
        mediaclip_tracks[-1].clips.append(clip)
    return mediaclip_tracks


def generate_avatar_tracks(avatar_list: List[AvatarClip]) -> List[Track]:
    """
    Generate avatar tracks from the list of avatar clips
    """
    avatar_tracks = []
    for idx, avatar in enumerate(avatar_list):

        transition = Transition()

        # TODO: these transitions for avatar clips looked little distracting. We should experiment and see if there are better transitions
        # Check if the current avatar clip doesn't have any preceding clip (threshold of 0.2s)
        # If yes apply popup transition to the current avatar clip
        # if idx > 0:
        #     if avatar.start_time - avatar_list[idx - 1].end_time > 0.2:
        #         transition = Transition(
        #             _in='carouselUpFast'
        #         )
        # # Check if the current avatar clip doesn't have any succeeding clip (threshold of 0.2s)
        # # If yes apply popdown transition to the current avatar clip
        # if idx < len(avatar_list) - 1:
        #     if avatar_list[idx + 1].start_time - avatar.end_time > 0.2:
        #         transition = Transition(
        #             _out='carouselDownFast'
        #         )

        clip = Clip(
            asset=VideoAsset(
                src=avatar.src,
                volume=1.0,
            ),
            start=avatar.start_time,
            length=avatar.end_time - avatar.start_time,
            offset=Offset(
                x=0.41,
                y=-0.24
            ),
            scale=0.148
            # transition=Transition(_in='fade')
        )

        if not avatar_tracks:
            avatar_tracks.append(Track(clips=[]))

        if avatar_tracks[-1].clips:
            # If the avatar clip overlaps with the previous avatar clip, create a new track
            if avatar.start_time < avatar_tracks[-1].clips[-1].start + avatar_tracks[-1].clips[-1].length:
                avatar_tracks.append(Track(clips=[]))
        avatar_tracks[-1].clips.append(clip)
    return avatar_tracks


def generate_avatar_introduction_tracks(avatar_introductions: List[AvatarIntroduction]) -> List[Track]:
    overlay_tracks: List[Track] = []
    for intro in avatar_introductions:
        clip = Clip(
            asset=VideoAsset(
                src=create_presigned_url(intro.src),
                volume=0.1
            ),
            start=intro.start_time,
            length=intro.end_time - intro.start_time
        )
        if not overlay_tracks:
            overlay_tracks.append(Track(clips=[]))
        overlay_tracks[-1].clips.append(clip)
    return overlay_tracks


def generate_text_slide_tracks(text_slides: List[TextSlide]) -> List[Track]:
    text_slide_tracks = [Track(clips=[])]
    for text_slide in text_slides:
        clip = Clip(
            asset=VideoAsset(
                src=text_slide.src,
                volume=0.1
            ),
            start=text_slide.start_time,
            length=text_slide.end_time - text_slide.start_time,
            transition=Transition(
                _in='fade',
                _out='fade'
            )
        )
        text_slide_tracks[0].clips.append(clip)
    return text_slide_tracks


def generate_diagram_tracks(diagrams: List[Diagram]) -> List[Track]:
    diagram_tracks = [Track(clips=[])]
    
    overviews = [d for d in diagrams if d.type in (DiagramType.LESSON_ORGANIZER, DiagramType.MIND_MAP) and sum([len(category.points) for category in d.data.categories])==0]
    overviews.sort(key=lambda x: x.start_time)

    for diagram in diagrams:
        clip = Clip(
            asset=VideoAsset(
                src=diagram.src,
                volume=0.1
            ),
            start=diagram.start_time,
            length=diagram.end_time - diagram.start_time,
            transition=Transition(
                **({} if diagram in overviews[1:] else {'_in':'fade'}),
                **({} if diagram==overviews[0] else {'out': 'fade'})
            )
        )
        diagram_tracks[0].clips.append(clip)
    return diagram_tracks


def generate_conclusion_slide_tracks(conclusion_slide: Optional[ConclusionSlide]) -> List[Track]:
    if conclusion_slide is None:
        return [Track(clips=[])]
    clip = Clip(    
        asset=VideoAsset(
            src=conclusion_slide.src,
            volume=0.1
        ),
        start=conclusion_slide.start_time,
        length=conclusion_slide.end_time - conclusion_slide.start_time,
        transition=Transition(
            # _in='fadeSlow'
        )
    )
    return [Track(clips=[clip])]


def generate_title_overlay_tracks(title_overlays: List[TitleOverlay]) -> List[Track]:
    """
    Generate title overlay tracks from the list of title overlays
    """
    title_overlay_tracks = []
    
    for title_overlay in title_overlays:
        if title_overlay.type == TitleOverlayType.SECTION_TITLE:
            title_tracks = [
                {"clips": [
                    {
                        "asset": {
                            "type": "text",
                            "text": title_overlay.text,
                            "alignment": {
                                "horizontal": "center",
                                "vertical": "center"
                            },
                            "font": {
                                "color": "#ffffff",
                                "family": "Montserrat SemiBold",
                                "size": "60",
                                "lineHeight": 1
                            },
                            "width": 1280,
                            "height": 720,
                            "background": {
                                "color": "#000000",
                                "opacity": 1.0
                            },
                            "stroke": {
                                "width": 1,
                                "color": "#ffffff"
                            }
                        },
                        "start": title_overlay.start_time,
                        "length": max(1.2, title_overlay.end_time - title_overlay.start_time),
                        "position": "center",
                        "transition": {
                            # "in": "fade",
                            "out": "fade"
                        }
                    }
                ]}
            ]
        elif title_overlay.type == TitleOverlayType.LESSON_TITLE:

            title_tracks = [
                {"clips": [
                    {
                        "asset": {
                            "type": "text",
                            "text": "",
                            "alignment": {
                                "horizontal": "center",
                                "vertical": "center"
                            },
                            "width": 1280,
                            "height": 720,
                            "background": {
                                "color": "#000000"
                            }
                        },
                        "start": 0,
                        "length": 2,
                        "transition": {
                            "out": "fade"
                        },
                        "opacity": 1.0
                    }
                ]},
                {"clips": [
                    {
                        "asset": {
                            "type": "text",
                            "text": title_overlay.text,
                            "alignment": {
                                "horizontal": "center",
                                "vertical": "center"
                            },
                            "font": {
                                "color": "#ffffff",
                                "family": "Montserrat SemiBold",
                                "size": "60",
                            },
                            "width": 1280,
                            "height": 720,
                            "background": {
                                "color": "#000000",
                                "opacity": 0.4,
                                "padding": 50
                            },
                            "stroke": {
                                "width": 1,
                                "color": "#ffffff"
                            }
                        },
                        "start": 0,
                        "length": 5,
                        "position": "center",
                        "transition": {
                            "out": "zoom"
                        }
                    }
                ]}
            ]

        title_overlay_tracks.extend(title_tracks)
    
    # Reverse the order of text_overlay_tracks
    title_overlay_tracks.reverse()
    
    return title_overlay_tracks


def replace_underscore_in_out(obj):
    if isinstance(obj, dict):
        new_obj = {}
        for key, value in obj.items():
            new_key = 'in' if key == '_in' else 'out' if key == '_out' else key
            new_obj[new_key] = replace_underscore_in_out(value)
        return new_obj
    elif isinstance(obj, list):
        return [replace_underscore_in_out(item) for item in obj]
    else:
        return obj


def generate_lesson_video_edit(lesson_video: LessonVideo, format: str = "mp4", resolution: str = "sd") -> Edit:
    """
    Generate the Shotstack Edit object for the lesson video
    """
    # We create tracks in bottom up order and finally reverse them

    # Create the audio tracks
    audio_tracks = generate_audio_tracks(sorted(lesson_video.audio, key=lambda x: x.start_time))

    # Create mediaclip tracks
    mediaclip_tracks = generate_mediaclip_tracks(sorted(lesson_video.clips, key=lambda x: x.start_time))

    # Create avatar tracks
    avatar_tracks = generate_avatar_tracks(sorted(lesson_video.avatar, key=lambda x: x.start_time))

    # Create avatar introduction tracks
    avatar_intro_tracks = generate_avatar_introduction_tracks(sorted(lesson_video.avatar_intros, key=lambda x: x.start_time))

    # Create text slide tracks
    text_slide_tracks = generate_text_slide_tracks(sorted(lesson_video.overlay_assets.text_slides, key=lambda x: x.start_time))

    # Create diagram tracks
    diagram_tracks = generate_diagram_tracks(sorted(lesson_video.overlay_assets.diagrams, key=lambda x: x.start_time))

    # Create conclusion slide tracks
    conclusion_slide_tracks = generate_conclusion_slide_tracks(lesson_video.overlay_assets.conclusion_slide)
    
    # Combine all tracks
    tracks = audio_tracks + mediaclip_tracks + text_slide_tracks + diagram_tracks + conclusion_slide_tracks + avatar_intro_tracks + avatar_tracks

    tracks = [track for track in tracks if len(track.clips)]
    # Reverse the tracks
    tracks.reverse()

    original_edit = Edit(
        timeline=Timeline(tracks=tracks),
        output=Output(
            format=format,
            resolution=resolution
        )
    )
    edit_json = original_edit.to_dict()

    # Create text overlay tracks
    title_overlay_tracks_json = generate_title_overlay_tracks(lesson_video.overlay_assets.title_overlays)

    # Add text overlay tracks to the beginning of the timeline
    if 'timeline' in edit_json and 'tracks' in edit_json['timeline']:
        edit_json['timeline']['tracks'] = title_overlay_tracks_json + edit_json['timeline']['tracks']
    else:
        logger.warning("Warning: 'timeline' or 'tracks' not found in original_edit_json")

    # Replace '_in' with 'in' in the entire JSON
    edit_json = replace_underscore_in_out(edit_json)

    return edit_json


def get_lesson_video_body(context: Context) -> LessonVideo:
    clips = load_json_from_s3(context.clips_path)['clips']
    avatar_assets = load_json_from_s3(context.avatar_assets_path)

    audio_clips = avatar_assets['avatar_assets']
    avatar_introductions = [AvatarIntroduction(**a) for a in load_json_from_s3(context.avatar_assets_path)['avatar_introductions']]
    overlay_assets = OverlaysData(**load_json_from_s3(context.text_overlays_path))

    media_clips = []
    for ii, clip in enumerate(clips):
        is_image = clip['media']['type'] == 'IMAGE' and not does_file_exist(context.media_path + f"videos/{clip['media']['id']}/{clip['media']['id']}.json")

        path = f"images/{clip['media']['id']}/{clip['media']['id']}.json" if is_image else f"videos/{clip['media']['id']}/{clip['media']['id']}.json"
        metadata = load_json_from_s3(context.media_path + path)
        choice = metadata['human_choice'] if metadata['human_choice'] is not None else metadata['qc_choice'] if metadata['qc_choice'] is not None else 0
        
        # logger.debug(clip['media']['type'], choice)
        media_clip = MediaClip(
            type='IMAGE' if is_image else 'VIDEO',
            start_time= clip['start_time'],
            end_time=clip['end_time'],
            transcript_snippet=clip['text'],
            contents=ImageClip(
                src=metadata['image'][choice]['src'] if metadata['image'][choice]['src'].startswith('http') else create_presigned_url(metadata['image'][choice]['src'], url_style='path', expiration=21600),
                description=metadata['image'][choice]['prompt'] if metadata['image'][choice]['prompt'] else ''
            ) if is_image else VideoClip(
                image_src='',
                src=create_presigned_url(metadata['videos'][-1]['src'], url_style='path', expiration=21600),
                description=metadata['videos'][-1]['prompt'] if metadata['videos'][-1]['prompt'] else '',
                duration=clip['end_time'] - clip['start_time']
            )
        )
        media_clips.append(media_clip)

    audio = []
    for audio_clip in audio_clips:
        audio.append(AudioClip(
            start_time=audio_clip['start_time'],
            end_time=audio_clip['end_time'],
            speaker=audio_clip['avatar_name'],  
            src=create_presigned_url(audio_clip['src'])
        ))

    avatar_clips = []
    avatar_assets_json = load_json_from_s3(context.avatar_assets_path)['avatar_assets']
    for avatar_clip in avatar_assets_json:
        if avatar_clip.get('avatar_clip', None) is not None:
            start_time = avatar_clip['start_time'] if avatar_clip.get('avatar_display_time', 0) == 0 else avatar_clip['avatar_display_time']
            avatar_clips.append(AvatarClip(
                start_time=start_time,
                end_time=avatar_clip['end_time'],
                src=create_presigned_url(avatar_clip['avatar_clip'], url_style='path'),
                speaker=avatar_clip['avatar_name']  # hard-coded, how is this used?
            ))

    # Process all overlay assets that have src fields
    if overlay_assets.text_slides:
        for slide in overlay_assets.text_slides:
            slide.src = create_presigned_url(slide.src)
    if overlay_assets.diagrams:
        for diagram in overlay_assets.diagrams:
            diagram.src = create_presigned_url(diagram.src)
    if overlay_assets.conclusion_slide:
        overlay_assets.conclusion_slide.src = create_presigned_url(overlay_assets.conclusion_slide.src)

    lesson_video_json = LessonVideo(
        context=context,
        clips=media_clips,
        audio=audio,
        avatar=avatar_clips,
        avatar_intros=avatar_introductions,
        overlay_assets=overlay_assets
    )
    return lesson_video_json

def append_video_data_to_sheet(context: Context, output: dict, section_wise_outputs: dict):
    sheet_info = get_sheet_info_by_subject(context.subject)["Fresh Generations"]
    spreadsheet_id = sheet_info['sheet_id']
    sheet_name     = sheet_info['sheet_name']
    
    common_cols = [
        "World History",
        "AP World History: Modern",
        "AP World " + output['metadata'].get('DomainId', '').split(':')[0],
        output['metadata'].get('ClusterId', ''),
        output['metadata'].get('DomainId', ''),
        *[v for v in output.values() if not isinstance(v, dict)],
    ]

    
    start_row = get_sheet_row_count(spreadsheet_id, sheet_name)
    for k, v in section_wise_outputs.items():
        row_data = [
            '=HYPERLINK("{}", "{}")'.format(v['video_url'].strip(), v['name'].replace("_", " ")),
            f"{v['start_time']} - {v['end_time']}",
            json.dumps(v['questions'], indent=2),
            '=HYPERLINK("{}", "{}")'.format(v['subtitles_url'].strip(), v['name'].replace("_", " ")),
        ]
        append_row_to_sheet(common_cols + row_data , spreadsheet_id, sheet_name)

    merge_cells(spreadsheet_id, sheet_name, start_row, start_row + len(section_wise_outputs), 0, len(common_cols), merge_type='MERGE_COLUMNS')
    
    # Generate sheet link with row range
    gid = get_worksheet_id(spreadsheet_id, sheet_name)
    end_row = start_row + len(section_wise_outputs) - 1
    sheet_link = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={gid}&range={start_row+1}:{end_row+1}"
    return sheet_link



def post_process(context: Context, video_url: str):
    overlays = OverlaysData(**load_json_from_s3(context.text_overlays_path))
    video_split_timings = {k.replace('Section: ', ''):v for k, v in overlays.video_splits.items()}
    questions = {section_title: [concept_questions.model_dump() for concept_questions in section_questions.values()] for section_title, section_questions in overlays.questions.items()}

    transcript = TranscriptOutput(**load_json_from_s3(context.transcripts_path))
    transcript_timings = TranscriptTiming(timings=load_json_from_s3(context.avatar_assets_path)['lesson_timings'])
    video_split_indexes = identify_video_split_indexes(transcript, transcript_timings)
    section_wise_outputs = {
        k: dict(
            name=k,
            start_time=0 if ii==0 else list(video_split_timings.values())[ii-1],
            end_time=v,
            start_index=0 if ii==0 else list(video_split_indexes.values())[ii-1]+1,
            end_index=video_split_indexes[k],
            questions=questions.get(k, {})
        )
        for ii, (k, v) in enumerate(video_split_timings.items())
    }

    title = context.subsection
    title = sanitize_path(title)
    base_s3_viewer_path = f'{context.subject}/{context.chapter}/{context.section}/{title}_{time.strftime("%Y-%m-%d_%H-%M")}'
    base_s3_viewer_path = sanitize_path(base_s3_viewer_path)

    transcript = load_json_from_s3(context.transcripts_path)['lesson_transcript']
    save_video(video_url, f'/tmp/{context.key}_{title}.mp4')
    time.sleep(2)
    upload_file_to_s3(f'/tmp/{context.key}_{title}.mp4', context.media_path + f'{title}.mp4') # Upload video to main bucket

    # generating and uploading section split videos
    video_url = upload_file_to_s3(f'/tmp/{context.key}_{title}.mp4', f'{base_s3_viewer_path}/{title}.mp4', S3_VIEWER_BUCKET, detect_mimetype=True) # Upload video for public view
    split_videos = split_lesson_video(f'/tmp/{context.key}_{title}.mp4', video_split_timings, context.key)
    for name, video in split_videos.items():
        name_cleaned = sanitize_path(name).replace("/", "_")
        section_wise_outputs[name]['video_url'] = upload_file_to_s3(video, f'{base_s3_viewer_path}/{name_cleaned}.mp4', S3_VIEWER_BUCKET, detect_mimetype=True)
        logger.info(f"For segment '{name}': {section_wise_outputs[name]['video_url']}")
        os.remove(video)
    os.remove(f'/tmp/{context.key}_{title}.mp4')
    
    # generating and uploading subtitles
    create_subtitles_file(transcript_timings, f'/tmp/{context.key}_{title}.srt')
    subtitles_url = upload_file_to_s3(f'/tmp/{context.key}_{title}.srt', f'{base_s3_viewer_path}/{title}.srt', S3_VIEWER_BUCKET)
    for name, video in section_wise_outputs.items():
        name_cleaned = sanitize_path(name).replace("/", "_")
        section_timings = TranscriptTiming(timings=transcript_timings.timings[video['start_index']:video['end_index']+1])
        section_timings = reset_timings(section_timings)
        create_subtitles_file(section_timings, f'/tmp/{context.key}_{name}.srt')
        section_wise_outputs[name]['subtitles_url'] = upload_file_to_s3(f'/tmp/{context.key}_{name}.srt', f'{base_s3_viewer_path}/{name_cleaned}.srt', S3_VIEWER_BUCKET)
        os.remove(f'/tmp/{context.key}_{name}.srt')
    os.remove(f'/tmp/{context.key}_{title}.srt')


    # generating and uploading thumbnails
    logger.info("Generating thumbnails...")
    thumbnails = get_thumbnails(context)
    local_img_path = f'/tmp/{context.key}_lesson_thumbnail.jpg'
    save_image(thumbnails['lesson_thumbnail'], local_img_path)
    thumbnails['lesson_thumbnail'] = upload_file_to_s3(local_img_path, f'{base_s3_viewer_path}/{title}.jpg', S3_VIEWER_BUCKET)
    for name, image_url in thumbnails['section_thumbnails'].items():
        name_cleaned = sanitize_path(name).replace("/", "_")
        local_img_path = f'/tmp/{context.key}_{name_cleaned}.jpg'
        save_image(image_url, local_img_path)
        thumbnails['section_thumbnails'][name] = upload_file_to_s3(local_img_path, f'{base_s3_viewer_path}/{name_cleaned}.jpg', S3_VIEWER_BUCKET)

    metadata = {k:v for k,v in context.lesson_plan.items() if k in ['DomainId', 'ClusterId']}

    output = {
        'metadata': metadata,
        'title': context.subsection,
        'url': video_url,
        'subtitles_url': subtitles_url,
        'subtitles_type': 'srt',
        'segment_urls': {k: v['video_url'] for k, v in section_wise_outputs.items()},
        'segment_subtitles_urls': {k: v['subtitles_url'] for k, v in section_wise_outputs.items()},
        'transcript': transcript,
        'thumbnails': thumbnails
    }

    sheet_link = append_video_data_to_sheet(context, output, section_wise_outputs)
    output['sheet_link'] = sheet_link  # Add sheet link to output

    return output

@with_logging_context(layer=LayerName.SHOTSTACK)
@exception_handler
def generate_lesson_video(output_path: str, output_type: str, inputs: dict, retry: int = 0) -> dict:
    context = Context(**inputs)
    logger.info(f"Generating Shotstack: {context.subsection}, {context.section}")
    lesson_video_body = get_lesson_video_body(context)

    # with open(f'./{context.key}.json', 'w') as f:
    #     json.dump(lesson_video_body.model_dump(), f, indent=2)

    lesson_video_edit = generate_lesson_video_edit(lesson_video=lesson_video_body, format='mp4', resolution='hd')

    # with open(f'./{context.key}_edit.json', 'w') as f:
    #     json.dump(lesson_video_edit, f, indent=2)

    shotstack_client = ShotstackClient()
    template_id = shotstack_client.create_template(lesson_video_edit, f'{context.key}_{int(time.time())}')
    logger.info(f"Template ID: {template_id}")
    time.sleep(10)
    render_id = shotstack_client.render_video(template_id) # type: ignore
    logger.info(f"Render ID: {render_id}")
    video_url = shotstack_client.get_video_url(render_id) # type: ignore
    logger.info(f"Video URL: {video_url}")

    if video_url is None and retry <6:
        logger.info(f"Retrying Shotstack: {context.subsection}. Retry {retry+1}")
        return generate_lesson_video(output_path, output_type, inputs, retry = retry+1)
    
    if video_url is None:
        output_data = {}
        logger.error(f"Shotstack generation failed even after 6 retries for {context.subsection}")
        raise Exception(f"Failed to generate shotstack for {context.subsection}. Retry {retry+1}")
    else:
        output_data = post_process(context, video_url)

    logger.info(f"Permanent URL: {output_data.get('url', None)}")
    logger.info(f"Sheet Link: {output_data.get('sheet_link', None)}")
    
    logger.info("Generating Lesson Report...")
    lesson_report = get_lesson_report(context)
    logger.info(f"Generated Lesson Report.")

    return {
        'lesson_video': {
        'url': video_url,
        'edit': lesson_video_edit, 
        'src': context.media_path + f'{sanitize_path(context.subsection)}.mp4',
        'output_data': output_data,
        'lesson_report': lesson_report
    }}


if __name__ == '__main__':
    from config.courses import get_execution_input
    from core.context import prep_content_gen_input
    setup_logging(level=logging.DEBUG)
    exec_input    = get_execution_input(
        subject = "AP World History - v6", 
        subsection = "Explain the systems of government employed by Chinese dynasties and how they developed over time."
    )
    context = Context(**prep_content_gen_input(exec_input))
    generate_lesson_video('', '', context.model_dump())
    # context = Context(**context)
    # print(get_sheet_row_count('16UfbuX-mfce8fzLh6MpRb7SShWMc6jMLJu1djrD1zsI', 'AP World History - Dump2'))
    # post_process(context, '<public mp4 url>')
