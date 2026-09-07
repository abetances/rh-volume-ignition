"""
Tests for chain verification (CP2 requirement).
"""

import pytest
from unittest.mock import Mock, patch
from src.scanner import Scanner
from src.providers import RPCProvider


class TestChainVerification:
    """Test chain verification features."""
    
    def test_scanner_has_chain_id_attribute(self):
        """Verify Scanner has _chain_id attribute."""
        scanner = Scanner()
        assert hasattr(scanner, '_chain_id')
    
    def test_scanner_chain_id_defaults_none(self):
        """Verify chain ID defaults to None."""
        scanner = Scanner()
        assert scanner._chain_id is None
    
    def test_rpc_provider_has_get_chain_id(self):
        """Verify RPCProvider has get_chain_id method."""
        provider = RPCProvider("test", "http://localhost:8545")
        assert hasattr(provider, 'get_chain_id')
        assert callable(provider.get_chain_id)
    
    def test_verify_chain_id_method_exists(self):
        """Verify Scanner has _verify_chain_id method."""
        scanner = Scanner()
        assert hasattr(scanner, '_verify_chain_id')
        assert callable(scanner._verify_chain_id)
    
    def test_verify_block_header_method_exists(self):
        """Verify Scanner has verify_block_header method."""
        scanner = Scanner()
        assert hasattr(scanner, 'verify_block_header')
        assert callable(scanner.verify_block_header)
