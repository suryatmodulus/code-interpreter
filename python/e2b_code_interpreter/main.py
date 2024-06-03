from __future__ import annotations

import json
import logging
import threading
import uuid

import requests

from concurrent.futures import Future
from typing import Any, Callable, List, Optional, Dict

from e2b import EnvVars, ProcessMessage, Sandbox
from e2b.constants import TIMEOUT

from e2b_code_interpreter.messaging import JupyterKernelWebSocket
from e2b_code_interpreter.models import KernelException, Execution, Result

logger = logging.getLogger(__name__)


class CodeInterpreter(Sandbox):
    """
    E2B code interpreter sandbox extension.
    """

    template = "code-interpreter-stateful-lab"

    def __init__(
        self,
        template: Optional[str] = None,
        api_key: Optional[str] = None,
        cwd: Optional[str] = None,
        env_vars: Optional[EnvVars] = None,
        timeout: Optional[float] = TIMEOUT,
        on_stdout: Optional[Callable[[ProcessMessage], Any]] = None,
        on_stderr: Optional[Callable[[ProcessMessage], Any]] = None,
        on_exit: Optional[Callable[[int], Any]] = None,
        **kwargs,
    ):
        super().__init__(
            template=template or self.template,
            api_key=api_key,
            cwd=cwd,
            env_vars=env_vars,
            timeout=timeout,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            on_exit=on_exit,
            **kwargs,
        )
        self.notebook = JupyterExtension(self, timeout=timeout)
        # Close all the websocket connections when the interpreter is closed
        self._process_cleanup.append(self.notebook.close)


class JupyterExtension:

    def __init__(self, sandbox: CodeInterpreter, timeout: Optional[float] = TIMEOUT):
        self._sandbox = sandbox
        self._kernel_id_set = Future()
        self._start_connecting_to_default_kernel(timeout=timeout)
        self._connected_kernels: Dict[str, Future[JupyterKernelWebSocket]] = {}
        self._default_kernel_id: Optional[str] = None

    def get_default_url(self) -> str:
        return f"https://{self._sandbox.get_hostname(8888)}/doc/tree/RTC:default.ipynb"

    def exec_cell(
        self,
        code: str,
        kernel_id: Optional[str] = None,
        on_stdout: Optional[Callable[[ProcessMessage], Any]] = None,
        on_stderr: Optional[Callable[[ProcessMessage], Any]] = None,
        on_result: Optional[Callable[[Result], Any]] = None,
        timeout: Optional[float] = TIMEOUT,
    ) -> Execution:
        """
        Execute code in a notebook cell.

        :param code: Code to execute
        :param kernel_id: The ID of the kernel to execute the code on. If not provided, the default kernel is used.
        :param on_stdout: A callback function to handle standard output messages from the code execution.
        :param on_stderr: A callback function to handle standard error messages from the code execution.
        :param on_result: A callback function to handle the result and display calls of the code execution.
        :param timeout: Timeout for the call

        :return: Result of the execution
        """
        kernel_id = kernel_id or self.default_kernel_id
        ws_future = self._connected_kernels.get(kernel_id)

        logger.debug(f"Executing code in kernel {kernel_id}")

        if ws_future:
            logger.debug(f"Using existing websocket connection to kernel {kernel_id}")
            ws = ws_future.result(timeout=timeout)
        else:
            logger.debug(f"Creating new websocket connection to kernel {kernel_id}")
            ws = self._connect_to_kernel_ws(kernel_id, None, timeout=timeout)

        message_id = ws.send_execution_message(code, on_stdout, on_stderr, on_result)
        logger.debug(
            f"Sent execution message to kernel {kernel_id}, message_id: {message_id}"
        )

        result = ws.get_result(message_id, timeout=timeout)
        logger.debug(
            f"Received result from kernel {kernel_id}, message_id: {message_id}, result: {result}"
        )

        nb = self._sandbox.filesystem.read(f"/home/user/default.ipynb", timeout=timeout)
        nb_parsed = json.loads(nb)
        cell = {
            "cell_type": "code",
            "metadata": {},
            "source": code,
        }

        outputs = []
        if result.logs.stdout:
            outputs.append(
                {"output_type": "stream", "name": "stdout", "text": result.logs.stdout}
            )
        if result.logs.stderr:
            outputs.append(
                {"output_type": "stream", "name": "stderr", "text": result.logs.stderr}
            )

        if result.results:
            outputs = [
                {
                    "output_type": (
                        "execute_result" if r.is_main_result else "display_data"
                    ),
                    "data": r.raw,
                    "metadata": {},
                }
                for r in result.results
            ]

        cell["execution_count"] = result.execution_count
        cell["outputs"] = outputs

        if nb_parsed["cells"] and not nb_parsed["cells"][-1]["source"]:
            nb_parsed["cells"][-1] = cell
        else:
            nb_parsed["cells"].append(cell)

        self._sandbox.filesystem.write(
            f"/home/user/default.ipynb", json.dumps(nb_parsed), timeout=timeout
        )
        return result

    @property
    def default_kernel_id(self) -> str:
        """
        Get the default kernel id

        :return: Default kernel id
        """
        if not self._default_kernel_id:
            logger.debug("Waiting for default kernel id")
            self._default_kernel_id = self._kernel_id_set.result()

        return self._default_kernel_id
    #
    # def create_kernel(
    #     self,
    #     name: str,
    #     path: str = "/home/user",
    #     kernel_name: str = "python3",
    #     timeout: Optional[float] = TIMEOUT,
    # ) -> str:
    #     """
    #     Creates a new kernel, this can be useful if you want to have multiple independent code execution environments.
    #
    #     The kernel can be optionally configured to start in a specific working directory and/or
    #     with a specific kernel name. If no kernel name is provided, the default kernel will be used.
    #     Once the kernel is created, this method establishes a WebSocket connection to the new kernel for
    #     real-time communication.
    #
    #     :param name: Name of the kernel
    #     :param path: Sets the current working directory for the kernel. Defaults to "/home/user".
    #     :param kernel_name: Specifies which kernel should be used, useful if you have multiple kernel types.
    #     :param timeout: Timeout for the kernel creation request.
    #     :return: Kernel id of the created kernel
    #     """
    #
    #     x = {
    #         "metadata": {
    #             "signature": "hex-digest",
    #             "kernel_info": {"name": kernel_name},
    #             "language_info": {
    #                 "name": kernel_name,
    #                 "version": "3.10.14",
    #             },  # TODO: get version
    #         },
    #         "nbformat": 4,
    #         "nbformat_minor": 0,
    #         "cells": [],
    #     }
    #
    #     self._sandbox.filesystem.write(
    #         f"/home/user/default.ipynb", json.dumps(x), timeout=timeout
    #     )
    #     self._sandbox.process.start("chmod 777 /home/user/default.ipynb")
    #
    #     data = {
    #         "name": name,
    #         "kernel": {"name": kernel_name},
    #         "notebook": {"name": "default.ipynb"},
    #         "path": path,
    #         "type": "notebook",
    #     }
    #
    #     logger.debug(f"Creating kernel with data: {data}")
    #
    #     response = requests.post(
    #         f"{self._sandbox.get_protocol()}://{self._sandbox.get_hostname(8888)}/api/sessions",
    #         json=data,
    #         timeout=timeout,
    #     )
    #     if not response.ok:
    #         raise KernelException(f"Failed to create kernel: {response.text}")
    #
    #     response_data = response.json()
    #     kernel_id = response_data["kernel"]["id"]
    #     session_id = response_data["id"]
    #
    #     logger.debug(f"Created kernel {kernel_id}, session {session_id}")
    #
    #     threading.Thread(
    #         target=self._connect_to_kernel_ws, args=(kernel_id, session_id, timeout)
    #     ).start()
    #
    #     return kernel_id

    def restart_kernel(
        self, kernel_id: Optional[str] = None, timeout: Optional[float] = TIMEOUT
    ) -> None:
        """
        Restarts an existing Jupyter kernel. This can be useful to reset the kernel's state or to recover from errors.

        :param kernel_id: The unique identifier of the kernel to restart. If not provided, the default kernel is restarted.
        :param timeout: The timeout in milliseconds for the kernel restart request.
        """
        kernel_id = kernel_id or self.default_kernel_id
        logger.debug(f"Restarting kernel {kernel_id}")

        self._connected_kernels[kernel_id].result().close()
        del self._connected_kernels[kernel_id]
        logger.debug(f"Closed websocket connection to kernel {kernel_id}")

        response = requests.post(
            f"{self._sandbox.get_protocol()}://{self._sandbox.get_hostname(8888)}/api/kernels/{kernel_id}/restart",
            timeout=timeout,
        )
        if not response.ok:
            raise KernelException(f"Failed to restart kernel {kernel_id}")

        logger.debug(f"Restarted kernel {kernel_id}")

        threading.Thread(
            target=self._connect_to_kernel_ws, args=(kernel_id, None, timeout)
        ).start()
    #
    # def shutdown_kernel(
    #     self, kernel_id: Optional[str] = None, timeout: Optional[float] = TIMEOUT
    # ) -> None:
    #     """
    #     Shuts down an existing Jupyter kernel. This method is used to gracefully terminate a kernel's process.
    #
    #     :param kernel_id: The unique identifier of the kernel to shutdown. If not provided, the default kernel is shutdown.
    #     :param timeout: The timeout for the kernel shutdown request.
    #     """
    #     kernel_id = kernel_id or self.default_kernel_id
    #     logger.debug(f"Shutting down kernel {kernel_id}")
    #
    #     self._connected_kernels[kernel_id].result().close()
    #     del self._connected_kernels[kernel_id]
    #     logger.debug(f"Closed websocket connection to kernel {kernel_id}")
    #
    #     response = requests.delete(
    #         f"{self._sandbox.get_protocol()}://{self._sandbox.get_hostname(8888)}/api/kernels/{kernel_id}",
    #         timeout=timeout,
    #     )
    #     if not response.ok:
    #         raise KernelException(f"Failed to shutdown kernel {kernel_id}")
    #
    #     logger.debug(f"Shutdown kernel {kernel_id}")
    #
    # def list_kernels(self, timeout: Optional[float] = TIMEOUT) -> List[str]:
    #     """
    #     Lists all available Jupyter kernels.
    #
    #     This method fetches a list of all currently available Jupyter kernels from the server. It can be used
    #     to retrieve the IDs of all kernels that are currently running or available for connection.
    #
    #     :param timeout: The timeout for the kernel list request.
    #     :return: List of kernel ids
    #     """
    #     response = requests.get(
    #         f"{self._sandbox.get_protocol()}://{self._sandbox.get_hostname(8888)}/api/kernels",
    #         timeout=timeout,
    #     )
    #
    #     if not response.ok:
    #         raise KernelException(f"Failed to list kernels: {response.text}")
    #
    #     return [kernel["id"] for kernel in response.json()]

    def close(self):
        """
        Close all the websocket connections to the kernels. It doesn't shutdown the kernels.
        """
        logger.debug("Closing all websocket connections")
        for ws in self._connected_kernels.values():
            ws.result().close()

    def _connect_to_kernel_ws(
        self,
        kernel_id: str,
        session_id: Optional[str],
        timeout: Optional[float] = TIMEOUT,
    ) -> JupyterKernelWebSocket:
        """
        Establishes a WebSocket connection to a specified Jupyter kernel.

        :param kernel_id: Kernel id
        :param session_id: Session id
        :param timeout: The timeout for the kernel connection request.

        :return: Websocket connection
        """
        if not session_id:
            session_id = uuid.uuid4()

        logger.debug(f"Connecting to kernel's ({kernel_id}) websocket")
        future = Future()
        self._connected_kernels[kernel_id] = future

        session_id = session_id or str(uuid.uuid4())
        ws = JupyterKernelWebSocket(
            url=f"{self._sandbox.get_protocol('ws')}://{self._sandbox.get_hostname(8888)}/api/kernels/{kernel_id}/channels",
            session_id=session_id,
        )

        ws.connect(timeout=timeout)
        logger.debug(f"Connected to kernel's ({kernel_id}) websocket.")

        future.set_result(ws)
        return ws

    def _start_connecting_to_default_kernel(
        self, timeout: Optional[float] = TIMEOUT
    ) -> None:
        """
        Start connecting to the default kernel in a separate thread to avoid blocking the main thread.
        :param timeout: Timeout for the call
        """
        logger.debug("Starting to connect to the default kernel")

        def setup_default_kernel():
            session_info = self._sandbox.filesystem.read(
                "/root/.jupyter/.session_info", timeout=timeout
            )

            if session_info is None and not self._sandbox.is_open:
                return

            data = json.loads(session_info)
            kernel_id = data["kernel"]["id"]
            session_id = data["id"]
            logger.debug(f"Default kernel id: {kernel_id}")
            self._connect_to_kernel_ws(kernel_id, session_id, timeout=timeout)
            self._kernel_id_set.set_result(kernel_id)

        threading.Thread(target=setup_default_kernel).start()
