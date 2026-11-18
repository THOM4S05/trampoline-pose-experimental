import json
from pathlib import Path

import pytest

from trampoline_pose.twist_width import attach


@pytest.mark.parametrize('job_id,expected,label',[
    ('001d3ba6ea5a484c94f6c69de04f5d7a',.5,'Half twist jump'),
    ('1008b53c4baf4deba0a4f268e8954d76',1.,'Full twist jump'),
    ('3ee0e567e5134cb88aba47e906763de3',1.5,'1½ twist jump')])
def test_recent_upright_jump_is_inferred_without_titles(job_id,expected,label):
    fixture=json.loads((Path(__file__).parent/'fixtures/straight-jumps'/(job_id+'.json')).read_text())
    result=attach(fixture['data'],{'skills':[fixture['skill']]})['skills'][0]['twist']
    assert result['candidate_count']==expected
    assert result['candidate_skill_identity']==label
    assert result['count'] is None
    assert result['status']=='tentative'
    assert result.get('detected_phases',result['completed_passages'])==expected*2
    if expected>=1:
        assert result['endpoint_facing_check']['matching_half_turn_parity']
        assert result['finish_completion_status']=='needs_review'


@pytest.mark.parametrize('failure',['facing_unknown','wrong_facing_parity','torso_outage','partial','somersault'])
def test_facing_phase_fallback_requires_independent_matching_evidence(failure):
    fixture=json.loads((Path(__file__).parent/'fixtures/straight-jumps/1008b53c4baf4deba0a4f268e8954d76.json').read_text())
    data,skill=fixture['data'],fixture['skill']
    end=skill['landing_contact']['timestamp_seconds']
    if failure in ('facing_unknown','wrong_facing_parity'):
        for f in data['frames']:
            if end-.05<=f['timestamp_seconds']<=min(end+.12,skill['visible_end_seconds']):
                j=f['joints'];ear_x=sum(j[n]['final']['x'] for n in ['left_ear','right_ear'])/2
                j['nose']['final']['x']=ear_x if failure=='facing_unknown' else ear_x-20
    elif failure=='torso_outage':
        data['frames'][200]['joints']['left_hip'].update(status='missing',final=dict(x=None,y=None))
    elif failure=='partial':skill['end_clipped']=True
    else:skill['rotation']['somersault_count']=1.
    result=attach(data,{'skills':[skill]})['skills'][0]['twist']
    assert result['candidate_count'] is None
    assert result.get('passage_method')!='upright_paired_width_phases_with_facing'
