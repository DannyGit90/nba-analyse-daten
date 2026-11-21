import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request
import injury_review as ir
import test_injury_review as original


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.ref = original.PersonnelTests()
        self.ref.setUp()

    def test_compact_header_and_sections(self):
        text = original.TEXT.replace(' ', '').replace('\n', '')
        self.assertEqual(ir.report_time(text), ir.published(original.URL))
        parts = ir.sections(text)
        self.assertEqual(len(parts), 4)
        sac = next(x for x in parts if x['team'] == 'SAC')
        self.assertEqual(sac['status'], 'not_submitted')
        self.assertEqual(parts[0]['status'], 'reported_raw')

    def test_four_digit_header_year(self):
        text = original.TEXT.replace('11/21/26 04:30 AM', '11/21/2026 04:30AM')
        result = ir.collect(self.ref.now, self.ref.loader, lambda b:text)
        self.assertEqual(result['status'], 'captured_raw')
        self.assertEqual(len(result['sections']), 4)

    def test_unicode_whitespace_and_zero_width(self):
        text = original.TEXT.replace('Injury Report', 'Injury\u200bReport').replace(' ', '\u00a0')
        self.assertEqual(ir.report_time(text), ir.published(original.URL))

    def test_conflicting_page_headers_rejected(self):
        with self.assertRaises(ValueError):
            ir.report_time(original.TEXT+'\nInjuryReport:11/21/2604:45AM')

    def test_official_nba_redirect_is_allowed(self):
        url = 'https://www.nba.com/players/injury-report'
        req = ir.OfficialRedirects().redirect_request(Request('https://official.nba.com/'),None,302,'Found',{},url)
        self.assertEqual(req.full_url, url)

    def test_untrusted_redirects_and_downgrades_rejected(self):
        for url in ['https://nba.com.evil.example/path','http://www.nba.com/path','https://www.nba.com@evil.example/path','https://www.nba.com:8080/path']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                ir.OfficialRedirects().redirect_request(Request('https://official.nba.com/'),None,302,'Found',{},url)

    def test_bad_initial_host_is_blocked_before_network(self):
        with patch.object(ir, 'build_opener') as opener:
            with self.assertRaises(ValueError):ir.download('https://example.com/report')
            opener.assert_not_called()

    def test_missing_header_diagnostic_is_bounded(self):
        result = ir.collect(self.ref.now, self.ref.loader, lambda b:'unknown format '+'x'*5000)
        preview = next(x['text_preview_ascii'] for x in result['attempts'] if 'text_preview_ascii' in x)
        self.assertLessEqual(len(preview), 322)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['sections'], [])

    def test_unavailable_report_does_not_claim_successful_team_lookup(self):
        with tempfile.TemporaryDirectory() as folder:
            self.ref.base(folder)
            payload = {'checked_at_utc':self.ref.now.isoformat(),'status':'unavailable','sections':[],'betting_release':False}
            ir.append_daily(folder, payload, self.ref.now)
            body = (Path(folder)/'daily/latest.md').read_text()
            self.assertIn('| BOS bei SAC | source_unavailable | source_unavailable |', body)
            self.assertNotIn('Offizielle Berichtstexte sind zugeordnet', body)
            self.assertNotIn('not_in_report', body)

    def test_stale_report_is_labelled_stale_per_team(self):
        with tempfile.TemporaryDirectory() as folder:
            self.ref.base(folder)
            payload = self.ref.payload();payload['status']='stale'
            ir.append_daily(folder, payload, self.ref.now)
            self.assertIn('| BOS bei SAC | source_stale | source_stale |',(Path(folder)/'daily/latest.md').read_text())


    def test_actual_pdf_reader_with_merged_text(self):
        import io
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        for header in ['InjuryReport:11/21/2604:30AM','InjuryReport:11/21/202604:30AM']:
            text = original.TEXT.replace(' ', '').replace('\n', '')
            text = text.replace('InjuryReport:11/21/2604:30AM', header)
            writer = PdfWriter()
            page = writer.add_blank_page(width=612, height=792)
            font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            stream = DecodedStreamObject()
            escaped = text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            stream.set_data(('BT /F1 10 Tf 20 700 Td ('+escaped+') Tj ET').encode())
            page[NameObject('/Contents')] = writer._add_object(stream)
            buffer = io.BytesIO();writer.write(buffer)
            extracted = ir.pdf_text(buffer.getvalue())
            self.assertEqual(ir.report_time(extracted), ir.published(original.URL))
            self.assertEqual(len(ir.sections(extracted)), 4)


if __name__ == '__main__':
    unittest.main()
