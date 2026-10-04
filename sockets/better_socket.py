from imports import (
    Logger,
    socket,
    threading
)

class BetterSock:
    def __init__(self, host='127.0.0.1', port=65432):
        self.logger = Logger("BetterSock")
        self.host = host
        self.port = port
        self.server_socket = None
        self.is_running = False
        
        # Callback placeholders
        self.on_connect_callback = None
        self.on_message_callback = None
        self.on_disconnect_callback = None

    # Decorators to easily register event handlers
    def on_connect(self, func):
        self.on_connect_callback = func
        return func

    def on_message(self, func):
        self.on_message_callback = func
        return func

    def on_disconnect(self, func):
        self.on_disconnect_callback = func
        return func

    def start(self):
        """Starts the server in a background thread so it doesn't block the main code."""
        self.is_running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Allows immediate reuse of the port after stopping the server
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen()
        
        # Run the acceptance loop in a separate thread
        threading.Thread(target=self._listen_loop, daemon=True).start()
        self.logger.log(f"Server started on {self.host}:{self.port}")

    def _listen_loop(self):
        while self.is_running:
            try:
                client_socket, client_address = self.server_socket.accept()
                # Handle each connected client in its own thread
                threading.Thread(
                    target=self._handle_client, 
                    args=(client_socket, client_address), 
                    daemon=True
                ).start()
            except Exception:
                break

    def _handle_client(self, client_socket, client_address):
        if self.on_connect_callback:
            self.on_connect_callback(client_address)

        while self.is_running:
            try:
                data = client_socket.recv(1024)
                if not data:
                    break # Client disconnected gracefully
                
                if self.on_message_callback:
                    # Parse data to string and provide a quick reply method
                    message = data.decode('utf-8')
                    def reply(text):
                        client_socket.sendall(text.encode('utf-8'))
                    
                    self.on_message_callback(message, reply, client_address)
                    
            except Exception as e:
                self.logger.log(f"Swallowed exception: {e}")

        client_socket.close()
        if self.on_disconnect_callback:
            self.on_disconnect_callback(client_address)

    def stop(self):
        """Stops the server and closes the socket."""
        self.is_running = False
        if self.server_socket:
            self.server_socket.close()
        self.logger.log("Server stopped.")