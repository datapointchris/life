from tests.utils.fake_ypl import FakeVideo
from tests.utils.fake_ypl import FakeYpl

VIDEO = FakeVideo('Wr1tt3nVid0', 'A made-up video', 'Its description.', 'A made-up channel', 61, 'what the video says')


def test_reads_share_one_sign_in_until_ypl_refuses_the_token():
    fake = FakeYpl()
    fake.add(VIDEO)
    client = fake.client()

    client.video_details(VIDEO.video_id)
    client.transcript(VIDEO.video_id)
    assert fake.tokens_issued == ['token-1']

    fake.tokens_revoked.add('token-1')
    details = client.video_details(VIDEO.video_id)

    assert details is not None and details.channel_title == VIDEO.channel_title
    assert fake.tokens_issued == ['token-1', 'token-2']
