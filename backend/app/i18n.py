"""Fixed co-pilot phrases (used for deterministic card captions and the offline co-pilot).

Placeholders are filled only with values computed in code.
"""
from __future__ import annotations

LANG_NAMES = {"en": "English", "hi": "Hindi (हिन्दी)", "ms": "Malay (Bahasa Melayu)"}

T: dict[str, dict[str, str]] = {
    "greeting": {
        "en": "I'm RecoverAI. I'm here to help you try to get your money back, step by step. You are not alone. What happened?",
        "hi": "मैं RecoverAI हूँ। मैं आपका पैसा वापस पाने की कोशिश में कदम-दर-कदम मदद करूँगा। आप अकेले नहीं हैं। क्या हुआ, बताइए?",
        "ms": "Saya RecoverAI. Saya di sini untuk membantu anda cuba mendapatkan semula wang anda, langkah demi langkah. Anda tidak keseorangan. Apa yang berlaku?",
    },
    "ask_evidence": {
        "en": "I'm sorry this happened. The first hour matters most. Please share the payment screenshot and any message from the scammer.",
        "hi": "मुझे अफ़सोस है कि ऐसा हुआ। पहला घंटा सबसे ज़रूरी है। कृपया भुगतान का स्क्रीनशॉट और ठग का कोई भी संदेश भेजिए।",
        "ms": "Saya kesal perkara ini berlaku. Jam pertama paling penting. Sila kongsi tangkapan skrin pembayaran dan sebarang mesej daripada penipu.",
    },
    "reading": {
        "en": "Thank you. I'm reading your evidence now…",
        "hi": "धन्यवाद। मैं आपके सबूत पढ़ रहा हूँ…",
        "ms": "Terima kasih. Saya sedang membaca bukti anda…",
    },
    "facts_ready": {
        "en": "Here is what I found. Please check it, especially any field marked in red or amber.",
        "hi": "मुझे यह जानकारी मिली। कृपया इसे जाँचिए, ख़ासकर लाल या पीले रंग वाले हिस्से।",
        "ms": "Ini yang saya temui. Sila semak, terutamanya medan bertanda merah atau kuning.",
    },
    "facts_confirm_first": {
        "en": "Please check the facts card and tap “Looks right” so I can build your action plan.",
        "hi": "कृपया जानकारी वाला कार्ड जाँचिए और “सही है” दबाइए, ताकि मैं आपकी कार्य-योजना बना सकूँ।",
        "ms": "Sila semak kad fakta dan tekan “Betul” supaya saya boleh sediakan pelan tindakan anda.",
    },
    "plan_ready": {
        "en": "Your action plan is ready. Do the first step right now.",
        "hi": "आपकी कार्य-योजना तैयार है। पहला कदम अभी उठाइए।",
        "ms": "Pelan tindakan anda sudah sedia. Lakukan langkah pertama sekarang.",
    },
    "generate_prompt": {
        "en": "When you are ready, tap “Generate all” and I will write every complaint and letter for you.",
        "hi": "जब आप तैयार हों, “सब तैयार करें” दबाइए — मैं सारी शिकायतें और पत्र लिख दूँगा।",
        "ms": "Apabila sedia, tekan “Jana semua” dan saya akan tulis semua aduan dan surat untuk anda.",
    },
    "drafts_ready": {
        "en": "All your documents are ready. You can copy them, download them, or download the evidence pack.",
        "hi": "आपके सभी दस्तावेज़ तैयार हैं। आप इन्हें कॉपी या डाउनलोड कर सकते हैं, या सबूत-पैक डाउनलोड कर सकते हैं।",
        "ms": "Semua dokumen anda sudah sedia. Anda boleh salin, muat turun, atau muat turun pek bukti.",
    },
    "consent_ask": {
        "en": "Shall I share this case with your bank's fraud team? They can request a temporary hold on the receiving account.",
        "hi": "क्या मैं यह केस आपके बैंक की फ्रॉड टीम को भेज दूँ? वे पैसा पाने वाले खाते पर अस्थायी रोक का अनुरोध कर सकते हैं।",
        "ms": "Boleh saya kongsi kes ini dengan pasukan penipuan bank anda? Mereka boleh meminta sekatan sementara pada akaun penerima.",
    },
    "sent_to_bank": {
        "en": "Sent to your bank. I'll tell you as soon as they respond.",
        "hi": "आपके बैंक को भेज दिया गया। जवाब आते ही मैं आपको बताऊँगा।",
        "ms": "Telah dihantar kepada bank anda. Saya akan maklumkan sebaik sahaja mereka menjawab.",
    },
    "consent_declined": {
        "en": "That's okay. Nothing was shared. You can share it later from here.",
        "hi": "कोई बात नहीं। कुछ भी साझा नहीं किया गया। आप बाद में यहीं से भेज सकते हैं।",
        "ms": "Tidak mengapa. Tiada apa yang dikongsi. Anda boleh kongsi kemudian dari sini.",
    },
    "bank_hold": {
        "en": "Your bank has placed a temporary hold request on the receiving account.",
        "hi": "आपके बैंक ने पैसा पाने वाले खाते पर अस्थायी रोक (होल्ड) का अनुरोध लगा दिया है।",
        "ms": "Bank anda telah membuat permintaan sekatan sementara ke atas akaun penerima.",
    },
    "bank_info": {
        "en": "Your bank needs a little more information: “{question}”. Please upload or type it here.",
        "hi": "आपके बैंक को थोड़ी और जानकारी चाहिए: “{question}”। कृपया यहाँ अपलोड करें या लिखें।",
        "ms": "Bank anda memerlukan sedikit maklumat lagi: “{question}”. Sila muat naik atau taip di sini.",
    },
    "bank_reject": {
        "en": "Your bank reviewed your case and did not place a hold. You can still follow the other steps.",
        "hi": "आपके बैंक ने आपका केस देखा और रोक नहीं लगाई। आप बाकी कदम अब भी उठा सकते हैं।",
        "ms": "Bank anda telah menyemak kes anda dan tidak membuat sekatan. Anda masih boleh ikut langkah lain.",
    },
    "escalation": {
        "en": "Your bank has not resolved your complaint in 30 days. You can now complain to the RBI Integrated Ombudsman. I have drafted the complaint for you.",
        "hi": "आपके बैंक ने 30 दिनों में आपकी शिकायत का समाधान नहीं किया। अब आप RBI एकीकृत लोकपाल (Ombudsman) से शिकायत कर सकते हैं। मैंने शिकायत का मसौदा तैयार कर दिया है।",
        "ms": "Bank anda belum menyelesaikan aduan anda dalam 30 hari. Anda kini boleh membuat aduan seterusnya. Saya telah sediakan draf aduan.",
    },
    "reminder_urgent": {
        "en": "Reminder: {label}. If you have not called yet, please call now.",
        "hi": "याद दिलाना: {label}। अगर अभी तक कॉल नहीं किया है, तो कृपया अभी करें।",
        "ms": "Peringatan: {label}. Jika anda belum menelefon, sila telefon sekarang.",
    },
    "deadline_passed": {
        "en": "A deadline has passed: {label}. Please complete the remaining steps as soon as you can.",
        "hi": "एक समय-सीमा निकल गई: {label}। कृपया बचे हुए कदम जल्द से जल्द पूरे करें।",
        "ms": "Satu tarikh akhir telah berlalu: {label}. Sila selesaikan langkah yang tinggal secepat mungkin.",
    },
    "warning": {
        "en": "Warning: this looks like a recovery scam. RecoverAI and official agencies never ask you to pay to get money back.",
        "hi": "चेतावनी: यह “रिकवरी स्कैम” लगता है। RecoverAI और सरकारी एजेंसियाँ पैसा वापस दिलाने के लिए कभी भुगतान नहीं माँगतीं।",
        "ms": "Amaran: ini kelihatan seperti penipuan pemulihan. RecoverAI dan agensi rasmi tidak pernah meminta anda membayar untuk mendapatkan semula wang.",
    },
    "warning_followup": {
        "en": "Please do not pay anyone who offers to recover your money. Do not share OTPs or passwords.",
        "hi": "पैसा वापस दिलाने का वादा करने वाले किसी को भी भुगतान न करें। OTP या पासवर्ड किसी को न बताएँ।",
        "ms": "Jangan bayar sesiapa yang menawarkan untuk mendapatkan semula wang anda. Jangan kongsi OTP atau kata laluan.",
    },
    "no_guarantee": {
        "en": "I can't promise you will get the money back. What helps most is reporting fast and completely: call the helpline, file the complaint, and tell your bank in writing.",
        "hi": "मैं वादा नहीं कर सकता कि पैसा वापस मिलेगा ही। सबसे ज़्यादा मदद जल्दी और पूरी रिपोर्ट करने से मिलती है: हेल्पलाइन पर कॉल करें, शिकायत दर्ज करें और बैंक को लिखित में बताएँ।",
        "ms": "Saya tidak boleh berjanji wang anda akan dikembalikan. Yang paling membantu ialah melapor dengan cepat dan lengkap: hubungi talian, buat aduan, dan maklumkan bank anda secara bertulis.",
    },
    "rule_prefix": {
        "en": "The rule says:",
        "hi": "नियम के अनुसार:",
        "ms": "Peraturan menyatakan:",
    },
    "status_next": {
        "en": "Here is where your case stands.",
        "hi": "यह रहा आपके केस का हाल।",
        "ms": "Ini status kes anda.",
    },
    "countries": {
        "en": "RecoverAI works for India and Malaysia today. More countries are coming soon.",
        "hi": "RecoverAI अभी भारत और मलेशिया के लिए काम करता है। और देश जल्द आ रहे हैं।",
        "ms": "RecoverAI kini berfungsi untuk India dan Malaysia. Lebih banyak negara akan datang.",
    },
    "danger": {
        "en": "If anyone is threatening you right now, please contact the local police immediately.",
        "hi": "अगर कोई अभी आपको धमका रहा है, तो तुरंत स्थानीय पुलिस से संपर्क करें।",
        "ms": "Jika sesiapa sedang mengugut anda sekarang, sila hubungi polis tempatan dengan segera.",
    },
    "retry": {
        "en": "Sorry, something went wrong on my side. Please try again.",
        "hi": "माफ़ कीजिए, मेरी तरफ़ से कुछ गड़बड़ हुई। कृपया फिर से कोशिश करें।",
        "ms": "Maaf, berlaku masalah di pihak saya. Sila cuba lagi.",
    },
    "never_pay": {
        "en": "Never pay anyone who offers to recover your money.",
        "hi": "पैसा वापस दिलाने का वादा करने वाले किसी को भी कभी भुगतान न करें।",
        "ms": "Jangan sekali-kali bayar sesiapa yang menawarkan untuk mendapatkan semula wang anda.",
    },
    # ---- CR-01 safe bank handoff
    "sent_to_sandbox": {
        "en": "Sent to the sandbox (test) — nothing was sent to a real bank. Reference {ref}.",
        "hi": "सैंडबॉक्स (टेस्ट) में भेजा गया — किसी असली बैंक को कुछ नहीं भेजा गया। रेफ़रेंस {ref}।",
        "ms": "Dihantar ke sandbox (ujian) — tiada apa yang dihantar kepada bank sebenar. Rujukan {ref}.",
    },
    "sent_to_bank_ref": {
        "en": "Sent to your bank. Reference {ref}. I'll tell you as soon as they respond.",
        "hi": "आपके बैंक को भेज दिया गया। रेफ़रेंस {ref}। जवाब आते ही मैं आपको बताऊँगा।",
        "ms": "Telah dihantar kepada bank anda. Rujukan {ref}. Saya akan maklumkan sebaik sahaja mereka menjawab.",
    },
    "withdraw_ask": {
        "en": "You can withdraw your consent for case {ref}. Please read what it means and confirm on the card.",
        "hi": "आप केस {ref} के लिए अपनी सहमति वापस ले सकते हैं। कृपया इसका मतलब पढ़ें और कार्ड पर पुष्टि करें।",
        "ms": "Anda boleh menarik balik persetujuan untuk kes {ref}. Sila baca maksudnya dan sahkan pada kad.",
    },
    "withdrawn": {
        "en": "Your bank has been told you withdrew consent (reference {ref}).",
        "hi": "आपके बैंक को बता दिया गया है कि आपने सहमति वापस ले ली है (रेफ़रेंस {ref})।",
        "ms": "Bank anda telah dimaklumkan bahawa anda menarik balik persetujuan (rujukan {ref}).",
    },
    "reply_fallback": {
        "en": "I have updated your case above. Please look at the card shown.",
        "hi": "मैंने ऊपर आपका केस अपडेट कर दिया है। कृपया दिखाया गया कार्ड देखें।",
        "ms": "Saya telah mengemas kini kes anda di atas. Sila lihat kad yang dipaparkan.",
    },
    "reply_fallback_next": {
        "en": "The most urgent step now: {step}.",
        "hi": "अभी सबसे ज़रूरी कदम: {step}।",
        "ms": "Langkah paling mendesak sekarang: {step}.",
    },
    "withdraw_not_shared": {
        "en": "This case has not been shared with a bank, so there is nothing to withdraw.",
        "hi": "यह केस किसी बैंक के साथ साझा नहीं हुआ है, इसलिए वापस लेने के लिए कुछ नहीं है।",
        "ms": "Kes ini belum dikongsi dengan bank, jadi tiada apa untuk ditarik balik.",
    },
    "demo_sandbox": {
        "en": "This looks like RecoverAI's demo evidence, so this case runs in sandbox mode. Nothing will be sent to a real bank.",
        "hi": "यह RecoverAI का डेमो सबूत लगता है, इसलिए यह केस सैंडबॉक्स मोड में चलेगा। किसी असली बैंक को कुछ नहीं भेजा जाएगा।",
        "ms": "Ini kelihatan seperti bukti demo RecoverAI, jadi kes ini berjalan dalam mod sandbox. Tiada apa akan dihantar kepada bank sebenar.",
    },
}


def t(key: str, lang: str, **kw: str) -> str:
    table = T.get(key, {})
    s = table.get(lang) or table.get("en") or key
    return s.format(**kw) if kw else s
