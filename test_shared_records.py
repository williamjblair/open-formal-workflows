import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import generate
import shared_records
from conjectures.core import save

class SharedRecordTests(unittest.TestCase):
    def test_queue_snapshot_produces_exact_context_without_reclassifying(self):
        snapshot={'prs':{'42':{'title':'Example','modified_files':['FormalConjectures/A.lean'],'status':'AwaitingAuthor'}}}
        basics={'42':{'headRefOid':'a'*40,'baseRefOid':'b'*40,'observedAt':'2026-09-09T00:00:00Z'}}
        value=shared_records.queue_context(snapshot,basics)
        self.assertEqual(value['pull_requests'][0]['head'],'a'*40)
        self.assertEqual(value['observed_at'],'2026-09-09T00:00:00Z')
        self.assertEqual(snapshot['prs']['42']['status'],'AwaitingAuthor')

    def test_build_uses_shared_reader_and_preserves_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            save(root/'snapshot.json',{'prs':{}});save(root/'pr_basics.json',{})
            with patch.object(shared_records,'HERE',root),patch.object(shared_records,'load',return_value={'status':'unavailable','runs':[],'message':'offline'}):
                value=shared_records.build()
            self.assertEqual(value['status'],'unavailable')
            with patch.object(generate,'HERE',root):self.assertEqual(generate.load_pilot(),value)
            value['runs']=[{'outcome':'pass'}];save(root/'toolkit-evidence.json',value)
            with patch.object(generate,'HERE',root),self.assertRaises(ValueError):generate.load_pilot()

    def test_renderer_handles_error_and_unavailable_without_acceptance(self):
        # Exercise the actual JS rendering functions with the same projection consumed by the browser.
        import subprocess
        template=generate.TEMPLATE
        functions=template[template.index('function humanize'):template.index('function renderMethod')]
        value={'status':'available','runs':[{'id':'run','kind':'verify','target':{'declaration':'E.a','commit':'a'*40},
            'summary':{'outcome':'error','policy_outcome':'not_evaluated'},'outcome':'error','producer':'local_operator',
            'applicability':'historical','changes':['head_changed']}]}
        script="const esc=x=>String(x);const emptyState=x=>x;const PILOT="+json.dumps(value)+';'+functions+"\nconsole.log(renderPilot());"
        text=subprocess.check_output(['node','-e',script],text=True)
        self.assertIn('not_evaluated',text);self.assertIn('historical',text)
