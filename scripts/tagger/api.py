"""API module for FastAPI"""
from typing import Callable
from threading import Lock
from secrets import compare_digest

from modules import shared
from modules.api.api import decode_base64_to_image
from modules.call_queue import queue_lock
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from scripts.tagger import utils
from scripts.tagger import api_models as models


class Api:
    """Api class for FastAPI"""
    def __init__(
        self, app: FastAPI, qlock: Lock, prefix: str = None
    ) -> None:
        if shared.cmd_opts.api_auth:
            self.credentials = {}
            for auth in shared.cmd_opts.api_auth.split(","):
                user, password = auth.split(":")
                self.credentials[user] = password

        self.app = app
        self.queue_lock = qlock
        self.prefix = prefix

        self.add_api_route(
            'interrogate',
            self.endpoint_interrogate,
            methods=['POST'],
            response_model=models.TaggerInterrogateResponse
        )

        self.add_api_route(
            'interrogators',
            self.endpoint_interrogators,
            methods=['GET'],
            response_model=models.InterrogatorsResponse
        )

        self.add_api_route(
            "unload-interrogators",
            self.endpoint_unload_interrogators,
            methods=["POST"],
            response_model=str,
        )

    def auth(self, creds: HTTPBasicCredentials = Depends(HTTPBasic())):
        if creds.username in self.credentials:
            if compare_digest(creds.password,
                              self.credentials[creds.username]):
                return True

        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={
                "WWW-Authenticate": "Basic"
            })

    def add_api_route(self, path: str, endpoint: Callable, **kwargs):
        if self.prefix:
            path = f'{self.prefix}/{path}'

        if shared.cmd_opts.api_auth:
            return self.app.add_api_route(path, endpoint, dependencies=[
                   Depends(self.auth)], **kwargs)
        return self.app.add_api_route(path, endpoint, **kwargs)

    def endpoint_interrogate(self, req: models.TaggerInterrogateRequest):
        if req.image is None:
            raise HTTPException(404, 'Image not found')

        if req.model not in utils.interrogators.keys():
            raise HTTPException(404, 'Model not found')

        image = decode_base64_to_image(req.image)
        interrogator = utils.interrogators[req.model]

        with self.queue_lock:
            ratings, tags = interrogator.interrogate(image)

        return models.TaggerInterrogateResponse(
            caption={
                **ratings,
                **interrogator.postprocess_tags(
                    tags,
                    req.threshold
                )
            })

    def endpoint_interrogators(self):
        return models.InterrogatorsResponse(
            models=list(utils.interrogators.keys())
        )

    def endpoint_unload_interrogators(self):
        unloaded_models = 0

        for i in utils.interrogators.values():
            if i.unload():
                unloaded_models = unloaded_models + 1

        return f"Successfully unload {unloaded_models} model(s)"


def on_app_started(_, app: FastAPI):
    Api(app, queue_lock, '/tagger/v1')
