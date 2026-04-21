#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demo script comparing AI-based vs rule-based offer extraction.
Run with: python demo_extraction.py
"""
import sys
import os
from lucid import extract_offers_from_message, _extract_offers_rule_based

# Test messages that show where AI extraction excels
test_messages = [
    {
        "message": "While $500 isn't really what I wanted, I'm willing to work with that if you can expedite delivery.",
        "description": "Implicit agreement with conditions"
    },
    {
        "message": "Our budget is stretched, but we could potentially stretch to $1200 if there were significant cost reductions elsewhere.",
        "description": "Conditional offer with nuance"
    },
    {
        "message": "I appreciate your position, but realistically we're looking at somewhere in the $3-5k range for this scope of work.",
        "description": "Range-based offer"
    },
    {
        "message": "Best we can do is knock off 15% from the original quote.",
        "description": "Implicit numeric offer"
    },
    {
        "message": "I'd love to move forward at the price point you mentioned, assuming the timeline works.",
        "description": "Acceptance with conditions"
    }
]

print("=" * 80)
print("OFFER EXTRACTION COMPARISON: AI vs Rule-Based")
print("=" * 80)

for test in test_messages:
    print(f"\n📝 Message: {test['message']}")
    print(f"   Context: {test['description']}")
    print("-" * 80)
    
    # Rule-based extraction
    rule_result = _extract_offers_rule_based(test['message'])
    print(f"\n🤖 Rule-Based Extraction:")
    print(f"   Has Offer: {rule_result['has_offer']}")
    print(f"   Keywords: {rule_result['keywords']}")
    print(f"   Numbers: {rule_result['numeric_values']}")
    
    # AI-based extraction (with fallback)
    print(f"\n🧠 AI-Based Extraction:")
    ai_result = extract_offers_from_message(test['message'])
    print(f"   Has Offer: {ai_result['has_offer']}")
    print(f"   Keywords: {ai_result['keywords']}")
    print(f"   Numbers: {ai_result['numeric_values']}")
    if ai_result.get('offer_summary'):
        print(f"   Summary: {ai_result['offer_summary']}")
    print(f"   Method: {ai_result['extraction_method']}")

print("\n" + "=" * 80)
print("Summary:")
print("- AI extraction uses semantic understanding to detect implicit offers")
print("- Rule-based extraction only finds explicit keywords and numbers")
print("- AI extraction falls back to rule-based if OpenAI API is unavailable")
print("=" * 80)
