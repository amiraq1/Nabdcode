import sys
import pytest
from unittest.mock import patch, MagicMock

import main

def test_tty_path_uses_renderer(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    
    # We want to mock render_final_answer to verify it's called
    with patch("rich.console.Console") as mock_console:
        with patch("ui.cc_style.render_final_answer") as mock_render:
            mock_render.return_value = "MARKDOWN_OUTPUT"
            
            # Setup fake state and ctx
            mock_state = MagicMock()
            mock_ctx = MagicMock()
            mock_loop = MagicMock()
            mock_engine = MagicMock()
            mock_outcome = MagicMock()
            mock_outcome.safe_message = "Test message"
            mock_outcome.final_answer = None
            mock_engine.run.return_value = mock_outcome
            mock_loop.return_value = mock_engine
            
            try:
                main._handle_one_shot_query(
                    ["dummy"], mock_state, mock_ctx, MagicMock(), mock_loop, Exception
                )
            except SystemExit:
                pass
                
            mock_render.assert_called_once_with("Test message")
            mock_console.return_value.print.assert_called_once_with("MARKDOWN_OUTPUT")

def test_pipe_path_stays_plain(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    
    with patch("ui.cc_style.render_final_answer", create=True) as mock_render:
        mock_state = MagicMock()
        mock_ctx = MagicMock()
        mock_loop = MagicMock()
        mock_engine = MagicMock()
        mock_outcome = MagicMock()
        mock_outcome.safe_message = "Test message"
        mock_outcome.final_answer = None
        mock_engine.run.return_value = mock_outcome
        mock_loop.return_value = mock_engine
        
        try:
            main._handle_one_shot_query(
                ["dummy"], mock_state, mock_ctx, MagicMock(), mock_loop, Exception
            )
        except SystemExit:
            pass
            
        mock_render.assert_not_called()
        mock_ctx.renderer.stream_chunk.assert_called_once_with("Test message")
