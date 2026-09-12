import os
import time
from typing import Union
import requests
import json
import logging
import shotstack_sdk as shotstack
from shotstack_sdk.api import edit_api
from shotstack_sdk.model.template import Template
from shotstack_sdk.model.template_render import TemplateRender

logger = logging.getLogger(__name__)

class ShotstackClient:
    def __init__(self):
        if 'SHOTSTACK_ENVIRONMENT' in os.environ and os.environ.get('SHOTSTACK_ENVIRONMENT') == 'prod':
            host = 'https://api.shotstack.io/v1'
            self.configuration = shotstack.Configuration(host = host)
            self.configuration.api_key['DeveloperKey'] = os.environ.get('SHOTSTACK_API_KEY_PROD')
        else:
            host = 'https://api.shotstack.io/stage'
            self.configuration = shotstack.Configuration(host = host)
            self.configuration.api_key['DeveloperKey'] = os.environ.get('SHOTSTACK_API_KEY')

    # TODO: make API request
    def create_template(self, edit, template_name: str) -> Union[str, None]:
        """
        Save the Shotstack Edit object as a template 
        Returns the template ID
        """
        # with shotstack.ApiClient(self.configuration) as api_client:
        #     api_instance = edit_api.EditApi(api_client)

        #     template = Template(
        #         name=template_name,
        #         template=edit
        #     )
        #     try:
        #         api_response = api_instance.post_template(template)
        #         logger.info("create template api response:", api_response)
        #         return api_response['response']['id']
        #     except Exception as e:
        #         logger.error(f"Unable to resolve API call in create_template: {e}")
        

        url = f"{self.configuration.host}/templates"
        headers = {
            "x-api-key": self.configuration.api_key['DeveloperKey'],
            "Content-Type": "application/json"
        }
        payload = {
            "name": template_name,
            "template": edit
        }

        
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response headers: {response.headers}")
        logger.info(f"Response content: {response.text}")
        response.raise_for_status()
        api_response = response.json()
        logger.info("create template api response:", api_response)
        return api_response['response']['id']
        
    
    # TODO: make API request
    def update_template(self, template_id: str, name: str, edit):
        """
        Update the Shotstack Edit object for the template ID
        """
        with shotstack.ApiClient(self.configuration) as api_client:
            api_instance = edit_api.EditApi(api_client)

            template = Template(
                name=name,
                template=edit
            )
            try:
                api_instance.put_template(template_id, template)
            except Exception as e:
                raise Exception(f"Unable to resolve API call: {e}")

    def render_video(self, template_id: str) -> Union[str, None]:
        """
        Render the video using the template ID
        Returns the render ID
        """
        with shotstack.ApiClient(self.configuration) as api_client:
            api_instance = edit_api.EditApi(api_client)

            template_render = TemplateRender(
                id=template_id
            )
            try:
                api_response = api_instance.post_template_render(template_render)
                logger.info(f"render video api response: {api_response}")
                return api_response['response']['id']
            except Exception as e:
                logger.error(f"Unable to resolve API call in render_video: {e}")

    def get_video_url(self, render_id: str) -> Union[str, None]:
        """
        Status poll and get the video URL using the render ID
        """
        # We retry upto 10 mins, this can be increased by increasing the NO_OF_RETRIES
        NO_OF_RETRIES = 20
        DURATION_BETWEEN_RETRIES = 30

        with shotstack.ApiClient(self.configuration) as api_client:
            api_instance = edit_api.EditApi(api_client)
            while NO_OF_RETRIES > 0:
                try:
                    logger.info(f"Polling for render status. Retries left: {NO_OF_RETRIES}")
                    api_response = api_instance.get_render(render_id, data=False, merged=True)
                    if api_response['response']['status'] == 'done':
                        logger.info("Render done. Fetching video URL")
                        return api_response['response']['url']
                    elif api_response['response']['status'] == 'failed':
                        logger.error(f"Render failed. Error message: {api_response['response']['error']}")
                        return None
                    else:
                        logger.info("Render not done. Retrying in 15 seconds")
                        time.sleep(DURATION_BETWEEN_RETRIES)
                        NO_OF_RETRIES -= 1

                except Exception as e:
                    logger.error(f"Unable to resolve API call in get_video_url: {e}")
                    break