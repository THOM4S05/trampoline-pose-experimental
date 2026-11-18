import json
from pathlib import Path

import pytest
import numpy as np

from trampoline_pose.skill_identification import centre,rotation_evidence
from trampoline_pose.twist_width import decode,WidthSettings
from trampoline_pose.somersault_twist import candidate


def fixtures():
    return json.loads((Path(__file__).parent/'fixtures/varsities.json').read_text())


@pytest.mark.parametrize('index,twists',[(6,.5),(8,.5),(10,.5),(11,1.)])
def test_reviewed_varsities_twist_passages(index,twists):
    item=next(f for f in fixtures() if f['index']==index)
    previous=decode(item['width_rows'],item['width_refs'],item['skill'])
    result=candidate(item['data'],item['width_rows'],item['skill'],previous,WidthSettings())
    assert result['candidate_count']==twists
    assert len(result['events'])==int(twists*2)
    assert 'body_relative_facing_candidate_needs_review' in result['review_reasons']


def test_native_axes_recover_two_flips_without_filling_torso_gap():
    item=next(f for f in fixtures() if f['index']==5)
    bounds=item['skill']['rotation']
    frames=[f for f in item['data']['frames'] if bounds['window_start_seconds']<=f['timestamp_seconds']<=bounds['window_end_seconds']]
    rotation=rotation_evidence(np.array([f['timestamp_seconds'] for f in frames]),
        np.array([centre(f,'shoulder') for f in frames]),np.array([centre(f,'hip') for f in frames]),1,.08,False)
    assert rotation['candidate_somersault_count']==2.
    assert rotation['candidate_somersault_quarters']==8
    assert rotation['somersault_count'] is None
    assert 'torso_gaps_or_jumps' in rotation['reasons']


def test_separated_final_jump_keeps_partial_tracking_qualification():
    item=next(f for f in fixtures() if f['index']==12)
    assert item['skill']['rotation']['candidate_somersault_count']==0.
    result=decode(item['width_rows'],item['width_refs'],item['skill'])
    assert result['completed_passages']==0
    assert result['count'] is None
    assert 'partial_flight' in result['reasons']
