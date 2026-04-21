# LUCID Negotiation Tool

This is an enhanced version of LUCID_TOOL_BACKEND that adds **automatic negotiation offer extraction and real-time display**.

## What's New

### Backend (Python/Flask)
- **Offer Extraction**: Automatically detects and extracts offers from conversation messages
- **Keyword Detection**: Identifies negotiation keywords (price, terms, offer, propose, etc.)
- **Numeric Parsing**: Extracts money amounts and percentages
- **Offer Tracking**: Maintains count of offers from each side

### Frontend (Qualtrics)
- **Offer Display Panel**: Shows latest offers from both user and AI side-by-side
- **Real-Time Updates**: Panel updates after each exchange
- **Visual Distinction**: Color-coded panels for user vs AI offers

## Project Structure

```
LUCID_NEGOTIATION_TOOL/
├── lucid.py                          # Backend Flask app with offer extraction
├── LUCID_Negotiation_Template.qsf    # Qualtrics template (negotiation-focused)
├── SETUP_INSTRUCTIONS.md              # Step-by-step setup guide
├── requirements.txt                  # Python dependencies
├── package.json                      # Node dependencies
└── vercel.json                       # Vercel deployment config
```

## Quick Start

### 1. Deploy Backend
```bash
# Push to GitHub and redeploy on Vercel
# The modified lucid.py includes offer extraction
```

### 2. Configure Vercel Environment Variables
```
OPENAI_API_KEY=sk-...your-key-here...
ALLOWED_ORIGINS=https://yourdomain.qualtrics.com
```

### 3. Update Qualtrics
See `SETUP_INSTRUCTIONS.md` for:
- HTML changes for offer display panel
- JavaScript changes for offer parsing

### 4. Test
Create a survey with negotiation scenario and verify offers appear

## Offer Extraction Example

**User says:** "I offer $500 for 30 days of delivery"
- **Keywords detected**: ["offer"]
- **Numbers detected**: ["$500", "30"]
- **Displayed**: "I offer $500 for 30 days of delivery"

**AI responds:** "That's interesting, but I'd suggest $800 for faster service"
- **Keywords detected**: ["suggest"]
- **Numbers detected**: ["$800"]
- **Displayed**: "I'd suggest $800 for faster service"

## Customization

### Add/Modify Offer Keywords
Edit `lucid.py`, `extract_offers_from_message()` function:
```python
offer_keywords = ['offer', 'propose', 'suggest', 'counter', 'bid', 'price', ...]
```

### Change Detection Logic
Modify regex patterns for numeric values or custom patterns:
```python
numeric_pattern = r'\$?\d+(?:,\d{3})*(?:\.\d{2})?|\d+%'
```

### Customize Panel Styling
Edit the CSS in SETUP_INSTRUCTIONS.md Step A

## API Response Format

The `/lucid` endpoint now returns:
```json
{
  "generated_text": "AI response text...",
  "offers": {
    "user_latest_offer": {
      "has_offer": true,
      "keywords": ["offer", "price"],
      "numeric_values": ["$500", "30"],
      "offer_phrases": ["I offer $500 for 30 days"]
    },
    "assistant_latest_offer": {
      "has_offer": true,
      "keywords": ["suggest"],
      "numeric_values": ["$800"],
      "offer_phrases": ["I'd suggest $800 for faster service"]
    },
    "user_offer_count": 2,
    "assistant_offer_count": 1
  },
  "used_temperature": 1.0
}
```

## Files Modified

### lucid.py
- Added `extract_offers_from_message()` function
- Added `get_latest_offers()` function
- Modified `/lucid` endpoint to call `get_latest_offers()` and include in response

### LUCID_Negotiation_Template.qsf
- Based on LUCID_Qualtrics_Template_1_-_One_Group_Design.qsf
- Ready for Qualtrics import
- Requires manual JavaScript updates (see SETUP_INSTRUCTIONS.md)

## Troubleshooting

**No offers showing?**
1. Check browser console for errors
2. Verify Network request shows `offers` in response
3. Ensure messages contain offer keywords or numbers

**Wrong offers detected?**
1. Check offer keywords in lucid.py
2. Add domain-specific keywords
3. Adjust regex patterns

**Vercel errors?**
1. Check environment variables are set correctly
2. Check Vercel logs in dashboard
3. Ensure OPENAI_API_KEY is valid

## Next Steps

- Add offer comparison metrics
- Store offer history for analysis
- Add confirmation/acceptance flow
- Create offer modification tracking
- Build negotiation analytics dashboard

## Support

See SETUP_INSTRUCTIONS.md for detailed implementation steps.
