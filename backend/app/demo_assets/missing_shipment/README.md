# Demo case: missing pallet shipment (fictional)

Every file here was generated for the EvidenceX demo. Names, plates, companies and
times are invented. This is not real evidence.

| File | Format | What EvidenceX extracts |
|---|---|---|
| delivery_receipt.pdf | PDF | receipt text with page and box locations (arrival time, plate, pallets) |
| gate_log_photo.png | image | OCR text regions from a gate log photo |
| dock_camera.mp4 | video | sampled frames with OCR text and their frame times |
| driver_call.wav | audio | a test tone with no speech, so the transcript is empty (warning `no_speech_detected`); it shows how a file without speech is handled |
| pallet_ledger.csv | CSV | rows and columns (shipment, pallets) |
| witness_email.eml | e-mail | headers and body text (witness account with a different time) |

With the default rule-based analysis (no AI), the verified run of this case produced
one proposed arrival event linking three accounts. After a reviewer confirmed it, there
were two possible time inconsistencies, each with alternative explanations. Results can
differ if the rules or the OCR engine version change, so check them in your own run
before you narrate them.
