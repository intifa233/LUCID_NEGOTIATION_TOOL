# LUCID Negotiation Tool - Setup & Implementation Guide

## Overview
This project adds **negotiation offer extraction and real-time display** to the LUCID_TOOL_BACKEND. It automatically detects offers from both user and AI, then displays them side-by-side during the conversation.

## What Was Done

### 1. **Backend Modifications** (lucid.py)
- ✅ Added `extract_offers_from_message()` function - Parses messages for offer keywords and numerical values
- ✅ Added `get_latest_offers()` function - Tracks latest offers from both sides
- ✅ Modified `/lucid` endpoint to extract and return offer data in responses

**New Response Format:**
```json
{
  "generated_text": "...",
  "offers": {
    "user_latest_offer": { keywords, numbers, offer_phrases },
    "assistant_latest_offer": { keywords, numbers, offer_phrases },
    "user_offer_count": 2,
    "assistant_offer_count": 1
  }
}
```

### 2. **Qualtrics Template Modifications** (Required - Manual Steps)

To add offer display to your Qualtrics survey, you need to:

#### Step A: Update the HTML (QuestionText for QID106)
Replace the existing chat container HTML with:

```html
<div id="chat-container">
  <div id="message-container">&nbsp;</div>
  
  <form id="chat-form">
    <textarea rows="2" placeholder="Type your message..." maxlength="1024" id="message-input"></textarea>
    <button type="submit" class="sbutton">
      <svg xmlns="http://www.w3.org/2000/svg" width="1.5em" viewBox="0 0 24 24" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" stroke="currentColor" height="1.5em" fill="none">
        <polyline points="18 15 12 9 6 15"></polyline>
      </svg>
    </button>
  </form>
  
  <!-- NEW: Offers Display Panel -->
  <div id="offers-panel" style="display:none;">
    <div class="offer-header">Current Offers</div>
    <div class="offer-side" style="width: 48%; display: inline-block; vertical-align: top; margin-right: 2%; padding: 10px; background-color: #fff; border: 1px solid #ddd; border-radius: 5px;">
      <div class="offer-label" style="color: #0066cc;">Your Offer:</div>
      <div id="user-offer-content" class="offer-content" style="background-color: #fffacd; padding: 8px; border-radius: 4px; font-size: 14px;">
        <span class="no-offer" style="color: #999; font-style: italic;">No offer yet</span>
      </div>
    </div>
    <div class="offer-side" style="width: 48%; display: inline-block; vertical-align: top; padding: 10px; background-color: #fff; border: 1px solid #ddd; border-radius: 5px;">
      <div class="offer-label" style="color: #d9534f;">AI Offer:</div>
      <div id="ai-offer-content" class="offer-content" style="background-color: #fffacd; padding: 8px; border-radius: 4px; font-size: 14px;">
        <span class="no-offer" style="color: #999; font-style: italic;">No offer yet</span>
      </div>
    </div>
  </div>
</div>
```

#### Step B: Update the JavaScript (QuestionJS for QID106)
In the `processNewMessage()` function, add this code to display offers:

**After the line `saveHistoriesToEmbeddedData();` (around line where AI message is logged), add:**

```javascript
// === NEGOTIATION OFFER DISPLAY ===
// Parse and display offers if the backend provided them
if (response.offers) {
    const offersData = response.offers;
    const offersPanel = document.getElementById('offers-panel');
    
    if (offersPanel) {
        // Get offer display elements
        const userOfferContent = document.getElementById('user-offer-content');
        const aiOfferContent = document.getElementById('ai-offer-content');
        
        // Display user's latest offer
        if (offersData.user_latest_offer && offersData.user_latest_offer.has_offer) {
            const userOffer = offersData.user_latest_offer;
            let offerText = '';
            
            if (userOffer.offer_phrases && userOffer.offer_phrases.length > 0) {
                offerText = userOffer.offer_phrases[0].substring(0, 150); // Limit text
            } else if (userOffer.numeric_values && userOffer.numeric_values.length > 0) {
                offerText = `Values: ${userOffer.numeric_values.join(', ')}`;
            } else if (userOffer.keywords && userOffer.keywords.length > 0) {
                offerText = `Keywords: ${userOffer.keywords.join(', ')}`;
            }
            
            if (userOfferContent) {
                userOfferContent.innerHTML = offerText || 'Offer detected';
            }
        }
        
        // Display AI's latest offer
        if (offersData.assistant_latest_offer && offersData.assistant_latest_offer.has_offer) {
            const aiOffer = offersData.assistant_latest_offer;
            let offerText = '';
            
            if (aiOffer.offer_phrases && aiOffer.offer_phrases.length > 0) {
                offerText = aiOffer.offer_phrases[0].substring(0, 150); // Limit text
            } else if (aiOffer.numeric_values && aiOffer.numeric_values.length > 0) {
                offerText = `Values: ${aiOffer.numeric_values.join(', ')}`;
            } else if (aiOffer.keywords && aiOffer.keywords.length > 0) {
                offerText = `Keywords: ${aiOffer.keywords.join(', ')}`;
            }
            
            if (aiOfferContent) {
                aiOfferContent.innerHTML = offerText || 'Offer detected';
            }
        }
        
        // Show the offers panel if at least one offer exists
        if ((offersData.user_latest_offer && offersData.user_latest_offer.has_offer) ||
            (offersData.assistant_latest_offer && offersData.assistant_latest_offer.has_offer)) {
            offersPanel.style.display = 'block';
        }
    }
}
// === END NEGOTIATION OFFER DISPLAY ===
```

## Setup Checklist

- [ ] Deploy modified `lucid.py` to Vercel (includes offer extraction)
- [ ] Set environment variables on Vercel:
  - `OPENAI_API_KEY` = your key
  - `ALLOWED_ORIGINS` = your Qualtrics domain
- [ ] Download `LUCID_Negotiation_Template.qsf`
- [ ] Import it into Qualtrics
- [ ] Add the offer display HTML from Step A above
- [ ] Add the offer display JavaScript from Step B above
- [ ] Update `LUCIDBackendURL` in Survey Flow to point to your backend
- [ ] Test the flow

## Features

### Automatic Offer Detection
Detects:
- **Keywords**: "offer", "propose", "suggest", "price", "deal", "terms", etc.
- **Numeric Values**: $100, 1000, 25%, etc.
- **Offer Phrases**: Extracts sentences containing offer language

### Real-Time Display
- Shows latest offers from both sides
- Updates with each response
- Side-by-side comparison
- Counter tracking number of offers made

### Customization
Edit keyword lists in `extract_offers_from_message()` to match your negotiation domain:
```python
offer_keywords = ['offer', 'propose', 'suggest', 'counter', 'bid', 'price', ...]
```

## Testing the Integration

1. Deploy backend to Vercel
2. Set environment variables
3. Open Qualtrics preview
4. Start a negotiation (both sides make offers)
5. Offers should appear in the panel below the chat

## Troubleshooting

**Offers not showing?**
- Check browser console for errors
- Verify offers are in API response (check Network tab)
- Ensure offer keywords match your domain

**Wrong offers being extracted?**
- Adjust keywords in `lucid.py`
- Offers must contain keywords or numeric values

## Next Steps

- Customize offer extraction for your specific domain
- Add visualization (charts, graphs)
- Store offer history for analysis
- Add offer comparison/delta tracking
