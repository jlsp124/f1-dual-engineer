# MIT License
#
# Copyright (c) [2024] [Ashwin Natarajan]
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# -------------------------------------- IMPORTS -----------------------------------------------------------------------

import logging
import webbrowser
from http import HTTPStatus
from typing import Any, Dict, Optional, Tuple

from apps.backend.state_mgmt_layer import SessionState
from apps.backend.state_mgmt_layer.intf import (PeriodicUpdateData,
                                                RaceInfoData,
                                                StreamOverlayData)
from lib.child_proc_mgmt import notify_parent_init_complete
from lib.config import PngSettings
from lib.dual_engineer.service import DualEngineerService
from lib.web_server import BaseWebServer, ClientType

from .request_handlers import RequestError, handleDriverInfoRequest

# -------------------------------------- GLOBALS -----------------------------------------------------------------------

# -------------------------------------- CLASS DEFINITIONS -------------------------------------------------------------

class TelemetryWebServer(BaseWebServer):
    """
    A web server class for handling telemetry-related web services and socket communications.

    This class sets up HTTP and WebSocket routes for serving telemetry data,
    static files, and managing client connections.

    Attributes:
        m_port (int): The port number on which the server will run.
        m_debug_mode (bool): Flag to enable/disable debug mode.
        m_app (Quart): The Quart web application instance.
        m_sio (socketio.AsyncServer): The Socket.IO server instance.
        m_sio_app (socketio.ASGIApp): The combined Quart and Socket.IO ASGI application.
        m_ver_str (str): The version string.
        m_logger (logging.Logger): The logger instance.
    """

    def __init__(self,
                 settings: PngSettings,
                 ver_str: str,
                 logger: logging.Logger,
                 session_state: SessionState,
                 dual_engineer_service: Optional[DualEngineerService] = None,
                 debug_mode: bool = False):
        """
        Initialize the TelemetryWebServer.

        Args:
            settings (PngSettings): App settings.
            ver_str (str): The version string.
            logger (logging.Logger): The logger instance.
            session_state (SessionState): Handle to the session state
            debug_mode (bool, optional): Enable or disable debug mode. Defaults to False.
        """
        super().__init__(
            port=settings.Network.server_port,
            ver_str=ver_str,
            logger=logger,
            bind_address=settings.Network.bind_address,
            client_event_mappings={
                ClientType.RACE_TABLE: ['frontend-update', 'race-table-update'],
                ClientType.PLAYER_STREAM_OVERLAY: ['stream-overlay-update'],
            },
            cert_path=settings.HTTPS.cert_path,
            key_path=settings.HTTPS.key_path,
            debug_mode=debug_mode)
        self.m_dual_engineer_service = dual_engineer_service
        self.m_show_start_sample_data = settings.StreamOverlay.show_sample_data_at_start
        self.m_session_state: SessionState = session_state
        self.m_disable_browser_autoload = settings.Display.disable_browser_autoload
        self.define_routes()
        self.register_post_start_callback(self._post_start)

    def define_routes(self) -> None:
        """
        Define all HTTP routes for the web server.

        This method calls sub-methods to set up file and data routes.
        """

        self._defineTemplateFileRoutes()
        self._defineDataRoutes()

    def _defineTemplateFileRoutes(self) -> None:
        """
        Define routes for rendering HTML templates.

        Sets up routes for the main index page and stream overlay page.
        """
        @self.http_route('/')
        async def index() -> str:
            """
            Render the primary dual-driver pit wall.

            Returns:
                str: Rendered HTML content for the index page.
            """
            return await self.render_template('dual-engineer.html', version=self.m_ver_str)

        @self.http_route('/driver-view')
        async def driverView() -> str:
            """Render the preserved upstream single-driver dashboard."""
            return await self.render_template('driver-view.html', live_data_mode=True, version=self.m_ver_str)

        @self.http_route('/eng-view')
        async def engineerView() -> str:
            """
            Render the engineer view page.

            Returns:
                str: Rendered HTML content for the stream overlay page.
            """
            return await self.render_template('eng-view.html', live_data_mode=True, version=self.m_ver_str)

        @self.http_route('/dual-engineer')
        async def dualEngineerView() -> str:
            """Render the dual-driver pit wall and analysis workspace."""
            return await self.render_template('dual-engineer.html', version=self.m_ver_str)

        @self.http_route('/eng-view/trackmap')
        async def engineerViewTrackmap() -> str:
            """
            Render the fullscreen track map page.

            Returns:
                str: Rendered HTML content for the fullscreen track map.
            """
            return await self.render_template('eng-view-trackmap.html', live_data_mode=True, version=self.m_ver_str)

        @self.http_route('/player-stream-overlay')
        async def playerStreamOverlay() -> str:
            """
            Render the player stream overlay page.

            Returns:
                str: Rendered HTML content for the stream overlay page.
            """
            return await self.render_template('player-stream-overlay.html')

    def _defineDataRoutes(self) -> None:
        """
        Define HTTP routes for retrieving telemetry and race-related data.

        Sets up endpoints for fetching race info, telemetry info,
        driver info, and stream overlay info.
        """
        @self.http_route('/telemetry-info')
        async def telemetryInfoHTTP() -> Tuple[str, int]:
            """
            Provide telemetry information via HTTP.

            Returns:
                Tuple[str, int]: JSON response and HTTP status code.
            """
            return PeriodicUpdateData(self.m_session_state).toJSON(), HTTPStatus.OK

        @self.http_route('/race-info')
        async def raceInfoHTTP() -> Tuple[str, int]:
            """
            Provide overall race statistics via HTTP.

            Returns:
                Tuple[str, int]: JSON response and HTTP status code.
            """
            return RaceInfoData(self.m_session_state).toJSON(), HTTPStatus.OK

        @self.http_route('/driver-info')
        async def driverInfoHTTP() -> Tuple[str, int]:
            """
            Provide driver information based on the index parameter.

            Returns:
                Tuple[str, int]: JSON response and HTTP status code.
            """
            result = handleDriverInfoRequest(self.m_session_state, self.request.args.get('index'))
            if result.ok:
                return result.data, HTTPStatus.OK
            http_status = {
                RequestError.MISSING_PARAM: HTTPStatus.BAD_REQUEST,
                RequestError.INVALID_PARAM: HTTPStatus.BAD_REQUEST,
                RequestError.NOT_FOUND:     HTTPStatus.NOT_FOUND,
            }[result.error]
            return {'error': result.detail}, http_status

        @self.http_route('/stream-overlay-info')
        async def streamOverlayInfoHTTP() -> Tuple[str, int]:
            """
            Provide stream overlay telemetry information via HTTP.

            Returns:
                Tuple[str, int]: JSON response and HTTP status code.
            """
            return StreamOverlayData(self.m_session_state, export_hud_data=True, export_pu_data=True) \
                        .toJSON(self.m_show_start_sample_data), HTTPStatus.OK

        @self.http_route('/api/dual-engineer/state')
        async def dualEngineerState() -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            data = self.m_dual_engineer_service.state_json()
            data["telemetry"] = PeriodicUpdateData(self.m_session_state, send_position_data=True).toJSON()
            return data, HTTPStatus.OK

        @self.http_route('/api/dual-engineer/selection', methods=['POST'])
        async def dualEngineerSelection() -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            if not self._same_origin_request():
                return {"error": "Cross-origin request rejected"}, HTTPStatus.FORBIDDEN
            try:
                payload = await self._bounded_json_request()
                state = self.m_dual_engineer_service.set_selection(
                    int(payload["driver_a_index"]), int(payload["driver_b_index"])
                )
            except (KeyError, TypeError, ValueError) as error:
                return {"error": str(error)}, HTTPStatus.BAD_REQUEST
            return state, HTTPStatus.OK

        @self.http_route('/api/dual-engineer/sessions')
        async def dualEngineerSessions() -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            return {"sessions": self.m_dual_engineer_service.sessions_json()}, HTTPStatus.OK

        @self.http_route('/api/dual-engineer/sessions/<session_uid>')
        async def dualEngineerSession(session_uid: str) -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            try:
                return self.m_dual_engineer_service.session_detail_json(session_uid), HTTPStatus.OK
            except (FileNotFoundError, ValueError) as error:
                return {"error": str(error)}, HTTPStatus.NOT_FOUND

        @self.http_route('/api/dual-engineer/sessions/<session_uid>/export', methods=['POST'])
        async def dualEngineerExport(session_uid: str) -> Any:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            if not self._same_origin_request():
                return {"error": "Cross-origin request rejected"}, HTTPStatus.FORBIDDEN
            try:
                archive = self.m_dual_engineer_service.export_session_zip(session_uid)
            except (OSError, ValueError) as error:
                return {"error": str(error)}, HTTPStatus.NOT_FOUND
            return await self.send_from_directory(archive.parent, archive.name, as_attachment=True)

        @self.http_route('/api/dual-engineer/sessions/<session_uid>/open', methods=['POST'])
        async def dualEngineerOpenFolder(session_uid: str) -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            if not self._same_origin_request() or not self._loopback_request():
                return {"error": "Open Session Folder is limited to this computer"}, HTTPStatus.FORBIDDEN
            try:
                folder = self.m_dual_engineer_service.open_session_folder(session_uid)
            except (OSError, ValueError) as error:
                return {"error": str(error)}, HTTPStatus.BAD_REQUEST
            return {"opened": str(folder)}, HTTPStatus.OK

        @self.http_route('/api/dual-engineer/careers')
        async def dualEngineerCareers() -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            return {"careers": self.m_dual_engineer_service.careers_json()}, HTTPStatus.OK

        @self.http_route('/api/dual-engineer/careers', methods=['POST'])
        async def dualEngineerCreateCareer() -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            if not self._same_origin_request():
                return {"error": "Cross-origin request rejected"}, HTTPStatus.FORBIDDEN
            try:
                return self.m_dual_engineer_service.create_career(
                    await self._bounded_json_request()
                ), HTTPStatus.CREATED
            except (TypeError, ValueError) as error:
                return {"error": str(error)}, HTTPStatus.BAD_REQUEST

        @self.http_route('/api/dual-engineer/careers/<int:career_id>')
        async def dualEngineerCareer(career_id: int) -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            try:
                return self.m_dual_engineer_service.career_detail_json(career_id), HTTPStatus.OK
            except KeyError as error:
                return {"error": str(error)}, HTTPStatus.NOT_FOUND

        @self.http_route('/api/dual-engineer/careers/<int:career_id>/import', methods=['POST'])
        async def dualEngineerImportCareer(career_id: int) -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            if not self._same_origin_request():
                return {"error": "Cross-origin request rejected"}, HTTPStatus.FORBIDDEN
            try:
                return self.m_dual_engineer_service.import_career_standings(
                    career_id, await self._bounded_json_request()
                ), HTTPStatus.OK
            except (KeyError, TypeError, ValueError) as error:
                return {"error": str(error)}, HTTPStatus.BAD_REQUEST

        @self.http_route('/api/dual-engineer/careers/<int:career_id>/activate', methods=['POST'])
        async def dualEngineerActivateCareer(career_id: int) -> Tuple[Dict[str, Any], int]:
            if not self.m_dual_engineer_service:
                return {"error": "Dual Engineer is disabled"}, HTTPStatus.SERVICE_UNAVAILABLE
            if not self._same_origin_request():
                return {"error": "Cross-origin request rejected"}, HTTPStatus.FORBIDDEN
            try:
                return self.m_dual_engineer_service.activate_career(career_id), HTTPStatus.OK
            except KeyError as error:
                return {"error": str(error)}, HTTPStatus.NOT_FOUND

    async def _bounded_json_request(self) -> Dict[str, Any]:
        """Read a small JSON object from a local/LAN dashboard request."""
        if self.request.content_length and self.request.content_length > 256 * 1024:
            raise ValueError("Request body is too large")
        payload = await self.request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        return payload

    def _same_origin_request(self) -> bool:
        origin = self.request.headers.get("Origin")
        return self.origin_allowed(origin, self.request.host)

    def _loopback_request(self) -> bool:
        return self.request.remote_addr in {"127.0.0.1", "::1", "localhost", None}

    async def _post_start(self) -> None:
        """Function to be called after the server starts serving."""
        notify_parent_init_complete()
        if not self.m_disable_browser_autoload:
            proto = 'https' if self.m_cert_path else 'http'
            webbrowser.open(f'{proto}://localhost:{self.m_port}', new=2)
