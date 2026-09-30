"""Offline boundary and workflow tests for reference-led narration. No model calls."""
import json
import ast
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import sys
import tempfile
import unittest
from types import SimpleNamespace
from typing import Dict, Optional
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.subject_profiles import PROFILES
from core.clients.lore import DEFAULT_CHOICE_MODEL, LoreClient, model_slug
from core.lore_editorial import (CRITERIA, Hook, Hooks, Narrative, Review, Source, StoryPlan,
    REFERENCE_DIR, approved_hook_for, generate_story, json_call, lesson_payload, reference_examples, validate_hook,
    validate_narrative, validate_plan, validate_review)
from core.lore_review import diagnostics
from core.hook_examples import youtube_hook_examples


def fixture():
    sources = [Source(id=f"S{i}", context="research", text=f"Supported fact {i}.") for i in range(3)]
    plan = dict(central_question="Why did the reading change?", significance="An unfamiliar effect.",
        premise="Resistance was expected.", answer="Cooling changed it.", necessary_explanation=["Compare readings"],
        factual_boundaries=["Zero was not reached"], opening_source_ids=["S0"],
        movements=[dict(id=f"m{i}",title=f"Movement {i}", purpose="Explain a comparison",
            source_ids=[f"S{i}"], understanding="How the reading matters", transition="The next test") for i in [1,2]],
        sample_end_movement_id="m2", omissions=[], limitations=[])
    hooks = dict(candidates=[dict(text=f"Candidate {i} asks an accessible question.",source_ids=["S0"],
        reason="Plain premise",factual_risk="None identified") for i in range(5)],selected_index=0,selection_reason="Clearest")
    narrative = dict(opening="The investigation began with a measurement.",
        sections=[dict(id="m1",text="They compared the readings."),dict(id="m2",text="The difference survived another test.")],
        closing="The question had an answer.\n\nGood night.",limitations=[])
    review = dict(criteria={k:dict(verdict="pass",reason="Supported by the supplied text") for k in CRITERIA},
        issues=[],required_revision=False,limitations=["No listening test"])
    return sources, plan, hooks, narrative, review


PASS_CHOICE=dict(usable=True,source_ids=['S0'],reason='The central topic invites curiosity')


def choice(checks=None, ranking=None):
    checks = checks or [dict(PASS_CHOICE) for _ in range(5)]
    return dict(candidate_checks=checks, ranking=ranking if ranking is not None else list(range(len(checks))))



def hook_response(h, u):
    request=json.loads(u)
    if request.get('approved_hook'):
        return h
    return {'candidates':[c['text'] for c in h['candidates']]}


class EditorialTests(unittest.TestCase):
    def test_ranking_cannot_override_unusable_claim(self):
        sources,p,h,n,r=fixture()
        checks=[dict(PASS_CHOICE) for _ in range(5)]
        checks[0]['usable']=False
        def call(s,u,t,m):
            return json.dumps({'hooks':hook_response(h,u),'hook-choice':choice(checks)}[t])
        result=generate_story(call,PROFILES['science'].voice,'Unseen','Science',sources,scope='hooks')
        self.assertEqual(result['hooks']['selected_index'],1)
        self.assertFalse(result['hook_selection']['candidate_checks'][0]['usable'])

    def test_uninteresting_openings_are_rejected(self):
        sources,p,h,n,r=fixture()
        checks=[{**PASS_CHOICE,'usable':False} for _ in range(5)]
        def call(s,u,t,m):
            return json.dumps({'hooks':hook_response(h,u),'hook-choice':choice(checks)}[t])
        result=generate_story(call,PROFILES['science'].voice,'Unseen','Science',sources,scope='hooks')
        self.assertEqual(result['status'],'needs_hook_revision')
        self.assertTrue(all(not c['usable'] for c in result['hook_selection']['candidate_checks']))
        self.assertEqual(result['hook'],'')

    def test_duplicate_choice_ranking_is_rejected(self):
        sources,p,h,n,r=fixture()
        def call(s,u,t,m):
            return json.dumps({'hooks':hook_response(h,u),
                'hook-choice':choice(ranking=[0,0,1,2,3])}[t])
        with self.assertRaisesRegex(ValueError,'rank every'):
            generate_story(call,PROFILES['science'].voice,'Unseen','Science',sources,scope='hooks')

    def test_hook_only_evaluation_is_fresh_and_saves_selection_without_story_plan(self):
        sources,p,h,n,r=fixture(); tags=[]
        def call(s,u,t,m):
            tags.append(t)
            self.assertIsNone(json.loads(u).get('approved_hook'))
            return json.dumps({'hooks':hook_response(h,u),'hook-choice':choice()}[t])
        with tempfile.TemporaryDirectory() as folder:
            result=generate_story(call,PROFILES['science'].voice,'The Letter That Split the Atom',
                'Science',sources,scope='hooks',artifact_dir=Path(folder))
            self.assertEqual(tags,['hooks','hook-choice'])
            self.assertEqual(result['status'],'hook_selection_passed')
            self.assertFalse(result['hook_locked'])
            self.assertEqual(json.loads((Path(folder)/'result.json').read_text())['hook'],result['hook'])

    def test_unsupported_hooks_stop_after_one_choice_call(self):
        sources,*_=fixture(); tags=[]
        checks=[{**PASS_CHOICE,'usable':False} for _ in range(5)]
        _,_,h,_,_=fixture()
        def call(s,u,t,m):
            tags.append(t)
            return json.dumps({'hooks':hook_response(h,u),'hook-choice':choice(checks)}[t])
        result=generate_story(call,PROFILES['history'].voice,'Thin topic','History',sources)
        self.assertEqual(tags,['hooks','hook-choice'])
        self.assertEqual(result['status'],'needs_hook_revision')
        self.assertEqual(result['text'],'')
        self.assertIsNone(result['plan'])

    def test_writing_profile_override_keeps_topic_in_its_content_subject(self):
        from unittest.mock import patch
        import tools.gen_lore_from_plan as cli
        plan = {"_meta": {"subject_profile": "science"}, "chapters": [{
            "chapter": "Nuclear fission", "videos": [{"title": "The Letter That Split the Atom",
                "lessons": [{"name": "Research", "concepts": ["Supported evidence."]}]}]}]}
        result = dict(text="A supported narrative.", status="candidate_model_review_passed",
                      prompt_version="test")
        def fake_generate(*args, **kwargs):
            args[9].mkdir(parents=True)  # The real story writer creates its editorial output directory.
            return result
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan_path = root / 'plan.json'
            plan_path.write_text(json.dumps(plan), encoding='utf-8')
            with patch.object(cli, 'LoreClient') as client, patch.object(
                    cli, 'generate_story', side_effect=fake_generate) as generate:
                client.return_value.provenance.return_value = {}
                client.return_value.model = 'offline-test'
                out = cli.generate(0, 0, root / 'generations', plan_path, profile='history', run_id='test')
            self.assertEqual(generate.call_args.args[1], PROFILES['history'].voice)
            self.assertEqual(out.relative_to(root / 'generations').parts[:2], ('science', 'letter-split'))
            meta = json.loads((out.parent / 'meta.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['content_subject'], 'science')
            self.assertEqual(meta['narration_profile'], 'history')
            self.assertFalse((root / 'generations/history').exists())

    def test_profile_specific_references_and_guidance_reach_writer_and_reviewer(self):
        sources,p,h,n,r=fixture()
        for profile in ('history','science'):
            requests={}; systems={}
            def call(s,u,t,m):
                requests[t]=json.loads(u); systems[t]=s
                return json.dumps({'plan':p,'hooks':hook_response(h,u),'hook-choice':choice(),'draft':n,'review':r}[t])
            generate_story(call,PROFILES[profile].voice,'Unseen',profile,sources)
            expected=reference_examples(profile)
            self.assertEqual(set(requests['hook-choice']), {'title','subject','research','candidates','output_schema'})
            self.assertNotIn('style_references', requests['hook-choice'])
            self.assertNotIn('youtube_hook_examples', requests['hooks'])
            self.assertNotIn('style_references', requests['hooks'])
            for item in youtube_hook_examples()['items']:
                self.assertIn(f"{item['id']}. {item['title']} ({item['channel']})\n{item['quote']}",
                              systems['hooks'])
            self.assertEqual(requests['hook-choice']['candidates'],[c['text'] for c in h['candidates']])
            self.assertNotIn('hook_brief',requests['hooks'])
            self.assertNotIn('hook_guidance',requests['hooks'])
            self.assertEqual(set(requests['hooks']['output_schema']['properties']), {'candidates'})
            self.assertEqual(requests['plan']['selected_hook'],h['candidates'][0]['text'])
            for tag in ('plan','draft','review'):
                self.assertEqual(requests[tag]['style_references'],expected)
                self.assertEqual(bool(requests[tag]['domain_guidance']),profile=='history')
            if profile=='history':
                self.assertTrue(all(name.startswith('history-') for name in expected))
                self.assertIn(requests['draft']['domain_guidance'],systems['draft'])
            else:
                self.assertEqual(set(expected),{'meitner-full.txt','bell-opening-sample.txt'})

    def test_rejected_hook_pool_stops_without_another_model_round(self):
        sources,p,h,n,r=fixture(); tags=[]
        rejected=choice([{**PASS_CHOICE,'usable':False} for _ in range(5)])
        def call(s,u,t,m):
            tags.append(t)
            return json.dumps({'plan':p,'hooks':hook_response(h,u),'hook-choice':rejected,'draft':n,'review':r}[t])
        result=generate_story(call,PROFILES['science'].voice,'Unseen','Science',sources)
        self.assertEqual(tags,['hooks','hook-choice'])
        self.assertEqual(result['status'],'needs_hook_revision')
        self.assertNotIn('draft',tags)
        self.assertNotIn('plan',tags)

    def test_sample_budget_applies_to_output_not_whole_plan(self):
        sources,p,h,n,r=fixture(); requests={}
        n['closing']=''; r['criteria']['ending']['verdict']='not_applicable'
        def call(s,u,t,m):
            requests[t]=json.loads(u)
            return json.dumps({'plan':p,'hooks':hook_response(h,u),'hook-choice':choice(),'draft':n,'review':r}[t])
        result=generate_story(call,PROFILES['science'].voice,'Unseen','Science',sources,
                              target_words=1400,scope='opening')
        self.assertEqual(requests['plan']['target_words'],4600)
        self.assertEqual(requests['plan']['requested_sample_words'],1400)
        self.assertEqual(requests['draft']['target_words'],1400)
        self.assertNotIn('Good night.',result['text'])

    def test_approved_registry_matches_reference_first_sentences(self):
        registry=json.loads((REFERENCE_DIR/'approved-hooks.json').read_text(encoding='utf-8'))
        for entry in registry['topics']:
            text=(REFERENCE_DIR/entry['reference_file']).read_text(encoding='utf-8')
            self.assertEqual(text.split('\n\n')[0].strip(),entry['text'])
            self.assertEqual(approved_hook_for(entry['title'])['text'],entry['text'])
        self.assertIsNone(approved_hook_for('An unseen topic'))

    def test_production_adapter_uses_real_output_schema_and_blocks_unresolved(self):
        # Execute the actual adapter and actual data-model definitions without initializing
        # unrelated AWS, image, and speech clients imported by the stage module.
        root=Path(__file__).resolve().parents[1]
        types_tree=ast.parse((root/'core/types.py').read_text(encoding='utf-8'))
        stage_tree=ast.parse((root/'stages/transcript.py').read_text(encoding='utf-8'))
        wanted={'TranscriptConcept','TranscriptSection','TranscriptLesson','TranscriptOutput'}
        env=dict(BaseModel=BaseModel,Dict=Dict,Optional=Optional,
            ConclusionSlideNew=BaseModel)
        exec(compile(ast.Module(body=[n for n in types_tree.body if isinstance(n,ast.ClassDef) and n.name in wanted],type_ignores=[]),'actual-models','exec'),env)
        calls=[]
        class Client:
            def __init__(self,*args): calls.append(('client',args))
            def provenance(self): return {'model':'test'}
        sources,p,h,n,r=fixture()
        result=dict(plan=p,narrative=n,hook='Approved hook.',status='candidate_model_review_passed',text='Candidate prose.')
        from config.subject_profiles import resolve_profile
        env.update(__file__=str(root/'stages/transcript.py'),Context=object,VideoPlan=object,Any=object,
            resolve_profile=resolve_profile,Source=Source,DEFAULT_MODEL='openai-group/gpt-6-astra',
            DEFAULT_CHOICE_MODEL=DEFAULT_CHOICE_MODEL,
            LoreClient=Client,generate_story=lambda *a,**kw:result,lesson_payload=lesson_payload,
            format_concept=lambda c:c.text,json=json,add_narration_pauses=lambda s:s,
            Path=Path,datetime=datetime,uuid4=uuid4)
        functions=[n for n in stage_tree.body if isinstance(n,ast.FunctionDef) and n.name in
                   {'get_lore_transcript_string','generate_lore_lesson_transcript'}]
        exec(compile(ast.Module(body=functions,type_ignores=[]),'actual-adapter','exec'),env)
        video=SimpleNamespace(simple_title='Test',lesson_title='Test',sections=[SimpleNamespace(
            simple_title='Research',section_title='Research',concepts=[SimpleNamespace(text='Evidence')])])
        with tempfile.TemporaryDirectory() as folder:
            params={'target_words':800,'editorial_root':folder}
            output=env['generate_lore_lesson_transcript'](SimpleNamespace(subject='Science'),video,params)
            self.assertIn('[Host]: Approved hook.',output['lesson_transcript'])
            self.assertEqual(list(output['lesson_transcript_breakdown']['sections']),['m1','m2'])
            env['add_narration_pauses']=lambda s:self.fail('Unresolved draft reached narration preparation')
            for status in ['needs_editorial_review','needs_hook_research','needs_hook_revision']:
                result['status']=status
                with self.assertRaisesRegex(RuntimeError,'before narration'):
                    env['generate_lore_lesson_transcript'](SimpleNamespace(subject='Science'),video,params)

    def test_gateway_model_names_are_not_double_prefixed(self):
        self.assertEqual(model_slug('claude-group/claude-opus-5-5'),'claude-group/claude-opus-5-5')
        self.assertEqual(model_slug('claude-opus-5-5'),'claude-group/claude-opus-5-5')
        self.assertEqual(model_slug('openai-group/gpt-6-astra'),'openai-group/gpt-6-astra')

    def test_plan_accounts_for_research_and_rejects_invented_ids(self):
        sources,p,*_=fixture()
        validate_plan(StoryPlan(**p),{s.id for s in sources})
        p['movements'][0]['source_ids']=['S999']
        with self.assertRaises(ValueError): validate_plan(StoryPlan(**p),{s.id for s in sources})

    def test_selected_source_cannot_also_be_omitted(self):
        sources,p,*_=fixture(); p['omissions']=[dict(source_id='S0',reason='incidental')]
        with self.assertRaises(ValueError): validate_plan(StoryPlan(**p),{s.id for s in sources})

    def test_reordered_missing_or_duplicate_movements_rejected(self):
        _,p,_,n,_=fixture()
        plan=StoryPlan(**p)
        for sections in [n['sections'][::-1],n['sections'][:1],n['sections']*2]:
            with self.assertRaises(ValueError):
                validate_narrative(Narrative(**{**n,'sections':sections}),plan.movements,'full','Hook.')

    def test_sample_cannot_masquerade_as_a_complete_story(self):
        _,p,_,n,_=fixture()
        with self.assertRaises(ValueError): validate_narrative(Narrative(**n),StoryPlan(**p).movements,'opening','Hook.')
        n['closing']=''
        with self.assertRaises(ValueError): validate_narrative(Narrative(**n),StoryPlan(**p).movements,'full','Hook.')

    def test_approved_hooks_are_not_rejected_by_word_count(self):
        for text in [
            'There is a limit to how cold anything can get—and near that limit, scientists found electricity could flow without resistance.',
            'Einstein helped create quantum physics, but its success left him questioning whether it described reality or only what scientists could observe.',
            'Around a century ago, a result challenged the estimate.']:
            validate_hook(Hook(text=text,source_ids=['S0'],reason='premise',factual_risk='none'),{'S0'})

    def test_review_cannot_invent_quotes_or_claim_false_pass(self):
        *_,n,r=fixture()
        r['issues']=[dict(location='m1',quote='An invented quote.',severity='major',problem='wrong',repair='correct')]
        r['required_revision']=True
        with self.assertRaises(ValueError): validate_review(Review(**r),Narrative(**n),'Hook.','full')
        r['issues'][0]['quote']='They compared the readings.'; r['required_revision']=False
        with self.assertRaises(ValueError): validate_review(Review(**r),Narrative(**n),'Hook.','full')

    def test_malformed_json_gets_one_contract_retry(self):
        _,_,h,_,_=fixture(); calls=[]
        def call(s,u,t,m):
            calls.append(json.loads(u)); return 'not JSON' if len(calls)==1 else json.dumps(h)
        json_call(call,'system',{},Hooks,'hooks',100)
        self.assertIn('contract_error_to_correct',calls[1])
        with self.assertRaises(ValueError): json_call(lambda *a:'not JSON','system',{},Hooks,'hooks',100)

    def test_full_pipeline_saves_provenance_and_keeps_locked_hook(self):
        sources,p,h,n,r=fixture(); tags=[]
        def call(s,u,t,m):
            tags.append(t)
            if t=='review':
                request=json.loads(u)
                self.assertTrue(request['assembled_transcript'].startswith(approved+'\n\n'))
                self.assertNotIn(approved,request['narrative']['opening'])
            return json.dumps({'plan':p,'hooks':hook_response(h,u),'draft':n,'review':r}[t])
        approved='An exact user-approved hook longer than fifteen words is preserved without being shortened by any automated sentence-length rule.'
        with tempfile.TemporaryDirectory() as folder:
            result=generate_story(call,PROFILES['science'].voice,'Title','Science',sources,
                approved_hook=approved,artifact_dir=Path(folder))
            self.assertTrue(result['text'].startswith(approved+'\n\n'))
            self.assertEqual(tags,['hooks','plan','draft','review'])
            self.assertTrue((Path(folder)/'prompts.json').exists())
            self.assertTrue((Path(folder)/'inputs.json').exists())
            payload=lesson_payload(result)
            self.assertEqual(list(payload['sections']),['m1','m2'])
            self.assertEqual(payload['sections']['m1']['explanations']['Movement 1']['figure_name'],'Host')

    def test_every_repair_is_reviewed_and_unresolved_findings_survive(self):
        sources,p,h,n,r=fixture(); tags=[]
        r['criteria']['source_fidelity']['verdict']='needs_work'; r['required_revision']=True
        r['issues']=[dict(location='m1',quote='They compared the readings.',severity='major',problem='Unsupported comparison',repair='Remove')]
        def call(s,u,t,m):
            tags.append(t); return json.dumps({'plan':p,'hooks':hook_response(h,u),'hook-choice':choice(),'draft':n,'repair':n,'review':r}[t])
        result=generate_story(call,PROFILES['science'].voice,'Title','Science',sources,max_revisions=1)
        self.assertEqual(tags[-3:],['review','repair','review'])
        self.assertEqual(result['status'],'needs_editorial_review')
        self.assertEqual(len(result['reviews']),2)

    def test_hook_repair_is_followed_by_body_review(self):
        sources,p,h,n,r=fixture(); tags=[]; reviews=0
        bad=json.loads(json.dumps(r)); bad['required_revision']=True
        bad['criteria']['hook_scope']['verdict']='needs_work'
        bad['issues']=[dict(location='hook',quote=h['candidates'][0]['text'],severity='major',problem='Vague',repair='Name subject')]
        fixed={**h['candidates'][0],'text':'Cooling changed the measurement.'}
        def call(s,u,t,m):
            nonlocal reviews
            tags.append(t)
            if t=='review':
                reviews+=1; return json.dumps(bad if reviews==1 else r)
            return json.dumps({'plan':p,'hooks':hook_response(h,u),'draft':n,'repair':n,
                'hook-repair':fixed,'hook-choice':choice([dict(PASS_CHOICE)] if 'hook-repair' in tags else None)}[t])
        result=generate_story(call,PROFILES['science'].voice,'Title','Science',sources)
        self.assertIn('hook-repair',tags)
        self.assertTrue(result['text'].startswith(fixed['text']))
        self.assertEqual(result['status'],'candidate_model_review_passed')

    def test_dull_hook_repair_cannot_pass_via_a_clean_body_review(self):
        sources,p,h,n,r=fixture(); reviews=0; repaired=False
        bad=json.loads(json.dumps(r)); bad['required_revision']=True
        bad['criteria']['hook_scope']['verdict']='needs_work'
        bad['issues']=[dict(location='hook',quote=h['candidates'][0]['text'],severity='major',problem='Vague',repair='Name subject')]
        fixed={**h['candidates'][0],'text':'Measurements can change.'}
        def call(s,u,t,m):
            nonlocal reviews, repaired
            if t=='hook-repair': repaired=True
            if t=='review':
                reviews+=1; return json.dumps(bad if reviews==1 else r)
            return json.dumps({'plan':p,'hooks':hook_response(h,u),'draft':n,'repair':n,
                'hook-repair':fixed,'hook-choice':choice([{**PASS_CHOICE,'usable':False}] if repaired else None)}[t])
        result=generate_story(call,PROFILES['science'].voice,'Title','Science',sources)
        self.assertEqual(result['status'],'needs_editorial_review')
        self.assertFalse(result['hook_repair_check']['usable'])

    def test_diagnostics_report_duplication_without_rewriting(self):
        paragraph='This is a repeated passage with enough words to make a twelve word overlap.'
        result=diagnostics(paragraph+'\n\n'+paragraph)
        self.assertEqual(result['duplicate_paragraphs'],[paragraph])
        self.assertTrue(result['repeated_12_word_sequences'])

    def test_client_rejects_truncation_and_records_model_parameters(self):
        class Response:
            ok=True; status_code=200
            def json(self): return {'choices':[{'finish_reason':'length','message':{'content':'partial prose'}}]}
        class Session:
            def post(self,*args,**kwargs):
                self.payload=kwargs['json']; return Response()
        client=LoreClient.__new__(LoreClient)
        client.model=client.review_model='openai-group/gpt-6-astra'; client.reasoning='medium'
        client.choice_model=DEFAULT_CHOICE_MODEL; client.choice_reasoning='medium'
        client.base_url='https://unused.invalid'; client.calls=[]; client.trace_dir=None; client.session=Session()
        with self.assertRaisesRegex(RuntimeError,'Incomplete'): client('system','user','draft',1234)
        self.assertEqual(client.session.payload['max_completion_tokens'],1234)
        self.assertNotIn('temperature',client.session.payload)
        self.assertEqual(len(client.calls),1)

    def test_choice_uses_smaller_model_without_changing_full_review(self):
        class Response:
            ok=True; status_code=200
            def json(self):
                return {'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
        class Session:
            def __init__(self): self.payloads=[]
            def post(self,*args,**kwargs):
                self.payloads.append(kwargs['json']); return Response()
        client=LoreClient.__new__(LoreClient)
        client.model=client.review_model='openai-group/gpt-6-astra'
        client.reasoning='high'; client.choice_model=DEFAULT_CHOICE_MODEL
        client.choice_reasoning='medium'; client.base_url='https://unused.invalid'
        client.calls=[]; client.trace_dir=None; client.session=Session()
        client('system','user','hook-choice',100)
        client('system','user','review',100)
        self.assertEqual([(p['model'],p['reasoning_effort']) for p in client.session.payloads],
                         [(DEFAULT_CHOICE_MODEL,'medium'),('openai-group/gpt-6-astra','high')])


if __name__=='__main__':
    unittest.main(verbosity=2)
