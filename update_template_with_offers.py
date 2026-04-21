#!/usr/bin/env python3
"""
Helper script to add offer display HTML and JavaScript to the LUCID Negotiation Template.
Properly handles JSON escaping when modifying the .qsf file.
"""
import json
import sys

# Path to the template file
TEMPLATE_PATH = "/Users/bxhan/Documents/GitHub/LUCID_NEGOTIATION_TOOL/LUCID_Negotiation_Template.qsf"

# Load the template
with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Find QID106 (the LUCID_TOOL question)
for element in data['SurveyElements']:
    if (element.get('Element') == 'SQ' and 
        element.get('PrimaryAttribute') == 'QID106'):
        
        payload = element['Payload']
        
        # ===== UPDATE QUESTION TEXT (HTML) =====
        old_html = payload['QuestionText']
        
        # Add the offers panel HTML after the chat form
        offers_html = '''\n
<div id="offers-panel" style="display:none; margin-top: 15px;">
<div style="font-weight: bold; margin-bottom: 10px;">📊 Current Offers</div>
<div style="display: flex; gap: 10px;">
<div style="flex: 1; padding: 10px; background-color: #e3f2fd; border: 1px solid #90caf9; border-radius: 5px;">
<div style="color: #0066cc; font-weight: bold; margin-bottom: 5px;">Your Offer</div>
<div id="user-offer-content" style="background-color: #fff; padding: 8px; border-radius: 3px; font-size: 14px;">
<span style="color: #999; font-style: italic;">No offer yet</span>
</div>
</div>
<div style="flex: 1; padding: 10px; background-color: #ffebee; border: 1px solid #ef9a9a; border-radius: 5px;">
<div style="color: #d9534f; font-weight: bold; margin-bottom: 5px;">AI Offer</div>
<div id="ai-offer-content" style="background-color: #fff; padding: 8px; border-radius: 3px; font-size: 14px;">
<span style="color: #999; font-style: italic;">No offer yet</span>
</div>
</div>
</div>
</div>'''
        
        # Insert the offers panel before the closing </div>
        new_html = old_html.replace('</form>\n</div>', f'</form>{offers_html}\n</div>')
        payload['QuestionText'] = new_html
        payload['QuestionText_Unsafe'] = new_html  # Update both fields
        
        # ===== UPDATE QUESTION JS =====
        old_js = payload['QuestionJS']
        
        # Add offer parsing code after saveHistoriesToEmbeddedData()
        offers_js = '''
             // === NEGOTIATION OFFER DISPLAY ===
             // Parse and display offers if the backend provided them
             if (response.offers) {
                 const offersData = response.offers;
                 const offersPanel = document.getElementById('offers-panel');
                 
                 if (offersPanel) {
                     const userOfferContent = document.getElementById('user-offer-content');
                     const aiOfferContent = document.getElementById('ai-offer-content');
                     
                     if (offersData.user_latest_offer && offersData.user_latest_offer.has_offer) {
                         const userOffer = offersData.user_latest_offer;
                         let offerText = '';
                         if (userOffer.offer_summary && userOffer.offer_summary.trim()) {
                             offerText = userOffer.offer_summary.substring(0, 200);
                         } else if (userOffer.numeric_values && userOffer.numeric_values.length > 0) {
                             offerText = 'Values: ' + userOffer.numeric_values.join(', ');
                         } else if (userOffer.keywords && userOffer.keywords.length > 0) {
                             offerText = 'Keywords: ' + userOffer.keywords.join(', ');
                         }
                         if (userOfferContent) {
                             userOfferContent.innerHTML = offerText || 'Offer detected';
                         }
                     }
                     
                     if (offersData.assistant_latest_offer && offersData.assistant_latest_offer.has_offer) {
                         const aiOffer = offersData.assistant_latest_offer;
                         let offerText = '';
                         if (aiOffer.offer_summary && aiOffer.offer_summary.trim()) {
                             offerText = aiOffer.offer_summary.substring(0, 200);
                         } else if (aiOffer.numeric_values && aiOffer.numeric_values.length > 0) {
                             offerText = 'Values: ' + aiOffer.numeric_values.join(', ');
                         } else if (aiOffer.keywords && aiOffer.keywords.length > 0) {
                             offerText = 'Keywords: ' + aiOffer.keywords.join(', ');
                         }
                         if (aiOfferContent) {
                             aiOfferContent.innerHTML = offerText || 'Offer detected';
                         }
                     }
                     
                     if ((offersData.user_latest_offer && offersData.user_latest_offer.has_offer) || (offersData.assistant_latest_offer && offersData.assistant_latest_offer.has_offer)) {
                         offersPanel.style.display = 'block';
                     }
                 }
             }
             // === END NEGOTIATION OFFER DISPLAY ==='''
        
        # Find and insert after saveHistoriesToEmbeddedData();
        insertion_point = "             // Save the updated logs to Qualtrics Embedded Data\n             saveHistoriesToEmbeddedData();"
        if insertion_point in old_js:
            new_js = old_js.replace(
                insertion_point,
                insertion_point + offers_js
            )
            payload['QuestionJS'] = new_js
            print("✓ Successfully added offer display JavaScript")
        else:
            print("✗ Could not find insertion point in JavaScript")
            sys.exit(1)
        
        print("✓ Successfully updated QuestionText with offers panel HTML")
        break

# Save the updated template
with open(TEMPLATE_PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=0)

print(f"\n✅ Template updated successfully: {TEMPLATE_PATH}")
print("The template now includes:")
print("  • Offers display panel in the HTML")
print("  • JavaScript to parse and display offers from the backend")
