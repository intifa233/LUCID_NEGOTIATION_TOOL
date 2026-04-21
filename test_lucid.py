# -*- coding: utf-8 -*-
"""
Unit tests for the LUCID negotiation tool, focusing on offer extraction.
"""
import unittest
import sys
import os
from unittest.mock import patch, MagicMock
import json

# Add the parent directory to the path to import lucid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lucid import extract_offers_from_message, get_latest_offers, _extract_offers_rule_based


class TestExtractOffersFromMessage(unittest.TestCase):
    """Test cases for the extract_offers_from_message function with AI-based extraction."""
    
    def _mock_openai_response(self, has_offer, offer_summary, numeric_values, keywords):
        """Helper to create a mocked OpenAI response."""
        return {
            'has_offer': has_offer,
            'offer_summary': offer_summary,
            'numeric_values': numeric_values,
            'keywords': keywords,
            'negotiation_elements': []
        }
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'})
    @patch('lucid.requests.post')
    def test_simple_offer_with_ai(self, mock_post):
        """Test extraction of a simple offer using AI."""
        ai_response = self._mock_openai_response(
            has_offer=True,
            offer_summary="Offering $500 for the project",
            numeric_values=['$500'],
            keywords=['offer']
        )
        
        # Mock the OpenAI API response
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'choices': [{'message': {'content': json.dumps(ai_response)}}]
            }
        )
        
        message = "I offer $500 for the project."
        result = extract_offers_from_message(message)
        
        self.assertTrue(result['has_offer'])
        self.assertEqual(result['extraction_method'], 'ai')
        self.assertEqual(result['role'], 'user')
        self.assertEqual(result['raw_message'], message)
        self.assertIn('$500', result['numeric_values'])
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': ''})
    def test_fallback_to_rule_based_no_api_key(self):
        """Test fallback to rule-based extraction when API key is missing."""
        message = "I offer $500 for the project."
        result = extract_offers_from_message(message)
        
        self.assertTrue(result['has_offer'])
        self.assertEqual(result['extraction_method'], 'rule_based')
        self.assertIn('offer', result['keywords'])
        self.assertIn('$500', result['numeric_values'])
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'})
    @patch('lucid.requests.post')
    def test_fallback_to_rule_based_api_error(self, mock_post):
        """Test fallback to rule-based extraction when API call fails."""
        mock_post.return_value = MagicMock(status_code=500)
        
        message = "I propose a deal at $750."
        result = extract_offers_from_message(message)
        
        self.assertTrue(result['has_offer'])
        self.assertEqual(result['extraction_method'], 'rule_based')
        self.assertIn('propose', result['keywords'])
        self.assertIn('deal', result['keywords'])
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'})
    @patch('lucid.requests.post')
    def test_fallback_to_rule_based_invalid_json(self, mock_post):
        """Test fallback when AI returns invalid JSON."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'choices': [{'message': {'content': 'not valid json'}}]
            }
        )
        
        message = "I counter with $600."
        result = extract_offers_from_message(message)
        
        self.assertTrue(result['has_offer'])
        self.assertEqual(result['extraction_method'], 'rule_based')
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'})
    @patch('lucid.requests.post')
    def test_complex_offer_with_ai(self, mock_post):
        """Test complex negotiation message with AI extraction."""
        ai_response = self._mock_openai_response(
            has_offer=True,
            offer_summary="Counteroffering $650 with improved payment terms and 15% margin",
            numeric_values=['$500', '$650', '15%'],
            keywords=['counter', 'offer', 'proposal', 'deal']
        )
        
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'choices': [{'message': {'content': json.dumps(ai_response)}}]
            }
        )
        
        message = "Thank you for your offer of $500. I counter with a proposal of $650, with better payment terms. This is my best deal at 15% margin."
        result = extract_offers_from_message(message)
        
        self.assertTrue(result['has_offer'])
        self.assertEqual(result['extraction_method'], 'ai')
        self.assertIn('$500', result['numeric_values'])
        self.assertIn('$650', result['numeric_values'])
        self.assertIn('15%', result['numeric_values'])
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'})
    @patch('lucid.requests.post')
    def test_non_offer_message_with_ai(self, mock_post):
        """Test that non-offer messages are correctly identified by AI."""
        ai_response = self._mock_openai_response(
            has_offer=False,
            offer_summary="",
            numeric_values=[],
            keywords=[]
        )
        
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'choices': [{'message': {'content': json.dumps(ai_response)}}]
            }
        )
        
        message = "The weather is nice today."
        result = extract_offers_from_message(message)
        
        self.assertFalse(result['has_offer'])
        self.assertEqual(result['extraction_method'], 'ai')
        self.assertEqual(result['keywords'], [])
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'})
    @patch('lucid.requests.post')
    def test_custom_role_parameter(self, mock_post):
        """Test that the role parameter is correctly stored."""
        ai_response = self._mock_openai_response(
            has_offer=True,
            offer_summary="I propose $500",
            numeric_values=['$500'],
            keywords=['propose']
        )
        
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'choices': [{'message': {'content': json.dumps(ai_response)}}]
            }
        )
        
        message = "I propose $500."
        
        user_result = extract_offers_from_message(message, role='user')
        self.assertEqual(user_result['role'], 'user')
        
        assistant_result = extract_offers_from_message(message, role='assistant')
        self.assertEqual(assistant_result['role'], 'assistant')


class TestRuleBasedExtraction(unittest.TestCase):
    """Test cases for the fallback rule-based extraction."""
    
    def test_simple_offer_rule_based(self):
        """Test rule-based extraction of simple offer."""
        message = "I offer $500 for the project."
        result = _extract_offers_rule_based(message)
        
        self.assertTrue(result['has_offer'])
        self.assertIn('offer', result['keywords'])
        self.assertIn('$500', result['numeric_values'])
        self.assertEqual(result['extraction_method'], 'rule_based')
    
    def test_multiple_keywords_rule_based(self):
        """Test rule-based extraction with multiple keywords."""
        message = "I propose a deal with a price of $1,500 and terms of 30 days."
        result = _extract_offers_rule_based(message)
        
        self.assertTrue(result['has_offer'])
        self.assertIn('propose', result['keywords'])
        self.assertIn('deal', result['keywords'])
        self.assertIn('price', result['keywords'])
        self.assertIn('terms', result['keywords'])
    
    def test_numeric_formats_rule_based(self):
        """Test rule-based extraction of various numeric formats."""
        test_cases = [
            ("$500", ['$500']),
            ("$1,500", ['$1,500']),
            ("$1,500.99", ['$1,500.99']),
            ("25%", ['25%']),
        ]
        
        for message, expected_numbers in test_cases:
            with self.subTest(message=message):
                result = _extract_offers_rule_based(message)
                for num in expected_numbers:
                    self.assertIn(num, result['numeric_values'])
    
    def test_empty_message_rule_based(self):
        """Test rule-based handling of empty messages."""
        result = _extract_offers_rule_based("")
        
        self.assertFalse(result['has_offer'])
        self.assertEqual(result['keywords'], [])
        self.assertEqual(result['numeric_values'], [])



class TestGetLatestOffers(unittest.TestCase):
    """Test cases for the get_latest_offers function."""
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': ''})
    def test_empty_conversation(self):
        """Test with an empty conversation history."""
        result = get_latest_offers([])
        
        self.assertIsNone(result['user_latest_offer'])
        self.assertIsNone(result['assistant_latest_offer'])
        self.assertEqual(result['user_offer_count'], 0)
        self.assertEqual(result['assistant_offer_count'], 0)
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': ''})
    def test_single_user_offer(self):
        """Test with a single user offer."""
        conversation = [
            {'role': 'user', 'content': 'I offer $500.'}
        ]
        result = get_latest_offers(conversation)
        
        self.assertIsNotNone(result['user_latest_offer'])
        self.assertIsNone(result['assistant_latest_offer'])
        self.assertEqual(result['user_offer_count'], 1)
        self.assertEqual(result['assistant_offer_count'], 0)
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': ''})
    def test_single_assistant_offer(self):
        """Test with a single assistant offer."""
        conversation = [
            {'role': 'assistant', 'content': 'I propose $600.'}
        ]
        result = get_latest_offers(conversation)
        
        self.assertIsNone(result['user_latest_offer'])
        self.assertIsNotNone(result['assistant_latest_offer'])
        self.assertEqual(result['user_offer_count'], 0)
        self.assertEqual(result['assistant_offer_count'], 1)
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': ''})
    def test_multiple_offers_both_sides(self):
        """Test with multiple offers from both sides."""
        conversation = [
            {'role': 'user', 'content': 'I offer $400.'},
            {'role': 'assistant', 'content': 'I counter with $600.'},
            {'role': 'user', 'content': 'I can go up to $500.'},
            {'role': 'assistant', 'content': 'Acceptable at $550.'}
        ]
        result = get_latest_offers(conversation)
        
        self.assertEqual(result['user_offer_count'], 2)
        self.assertEqual(result['assistant_offer_count'], 2)
        
        # Check latest offers
        self.assertIsNotNone(result['user_latest_offer'])
        self.assertIsNotNone(result['assistant_latest_offer'])
        
        # Latest user offer should be $500
        self.assertIn('$500', result['user_latest_offer']['numeric_values'])
        
        # Latest assistant offer should be $550
        self.assertIn('$550', result['assistant_latest_offer']['numeric_values'])
    
    @patch.dict(os.environ, {'OPENAI_API_KEY': ''})
    def test_non_offer_messages_filtered(self):
        """Test that non-offer messages are properly filtered out."""
        conversation = [
            {'role': 'user', 'content': 'Hello, how are you?'},
            {'role': 'assistant', 'content': 'I am fine. I propose $600.'},
            {'role': 'user', 'content': 'The weather is nice.'},
            {'role': 'user', 'content': 'I offer $500.'},
        ]
        result = get_latest_offers(conversation)
        
        # Should only count actual offers
        self.assertEqual(result['user_offer_count'], 1)  # Only the $500 offer
        self.assertEqual(result['assistant_offer_count'], 1)  # Only the $600 offer


if __name__ == '__main__':
    unittest.main()
