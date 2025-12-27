import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.graphiti_client import GraphitiWrapper

@pytest.mark.asyncio
async def test_retry_logic():
    """Test that the client retries on 503/500 errors"""
    
    # Mock the super().handle_async_request
    # We need to mock it on the instance of CleaningHTTPTransport
    # But CleaningHTTPTransport is defined inside __init__, so it's tricky to patch directly.
    # Instead, we can instantiate GraphitiWrapper and then patch the transport of its http_client.
    
    # However, GraphitiWrapper.__init__ creates the client.
    # Let's try to patch httpx.AsyncHTTPTransport.handle_async_request globally for this test
    # or better, since we modified the class inside __init__, we need to test that specific class.
    
    # Actually, since CleaningHTTPTransport is defined inside __init__, we can't easily import it.
    # But we can inspect the http_client of the created wrapper.
    
    wrapper = GraphitiWrapper()
    # The wrapper has .client, which has .llm_client, which has .client (AsyncOpenAI), which has ._client (httpx.AsyncClient)
    # But wait, our custom transport is used in the AsyncOpenAI client.
    
    # Let's find the transport
    # graphiti_client.client (Graphiti) -> .llm_client (OpenAIClient) -> .client (AsyncOpenAI) -> ._client (httpx.AsyncClient) -> ._transport (CleaningHTTPTransport)
    
    transport = wrapper.client.llm_client.client._client._transport
    
    # Mock the super().handle_async_request method
    # Since we can't easily call super() in a mock, we'll mock the method we overrode?
    # No, we want to test the method we wrote.
    # The method calls super().handle_async_request.
    
    # We can patch `httpx.AsyncHTTPTransport.handle_async_request`
    with patch('httpx.AsyncHTTPTransport.handle_async_request', new_callable=AsyncMock) as mock_super:
        # Scenario: 2 failures then success
        # Use 503 (Service Unavailable) instead of 404 because 4xx errors are not retried
        mock_super.side_effect = [
            httpx.Response(503, content=b"Service unavailable"),
            httpx.Response(500, content=b"Internal error"),
            httpx.Response(200, content=b'{"choices": [{"message": {"content": "Success"}}]}')
        ]
        
        # We also need to speed up the sleep to avoid waiting 10 seconds
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            request = httpx.Request("POST", "http://test")
            response = await transport.handle_async_request(request)
            
            assert response.status_code == 200
            assert mock_super.call_count == 3
            assert mock_sleep.call_count == 2 # Should sleep twice

@pytest.mark.asyncio
async def test_retry_timeout():
    """Test that the client gives up after timeout"""
    wrapper = GraphitiWrapper()
    transport = wrapper.client.llm_client.client._client._transport
    
    with patch('httpx.AsyncHTTPTransport.handle_async_request', new_callable=AsyncMock) as mock_super:
        # Always fail with 503 (Service Unavailable) which will be retried
        mock_super.return_value = httpx.Response(503, content=b"Service unavailable")
        
        # Mock time to simulate timeout
        # We need to mock time.time() to increment
        with patch('time.time') as mock_time:
            # Start at 0, then increment by 10s each call
            # We need enough values to prevent StopIteration during loop
            mock_time.side_effect = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]
            
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                request = httpx.Request("POST", "http://test")
                response = await transport.handle_async_request(request)
                
                # Should return the last failed response (503)
                assert response.status_code == 503
                # Should have tried a few times until timeout
                assert mock_super.call_count >= 1
                assert mock_sleep.call_count >= 1
