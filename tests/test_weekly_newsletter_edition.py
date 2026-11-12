"""Regression checks for late publications, one edition and the approved design."""
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import MagicMock
from newsletter_edition import sync_weekly_draft, RECALL_POSITION, existing_images, preview_subject
from youdle_email_template import render_youdle_newsletter_html

NOW = datetime(2026, 11, 12, 4, 0, tzinfo=timezone.utc)
STAMP = NOW.isoformat()

class Result:
    def __init__(self, data): self.data = data

class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters, self.mode, self.values = [], 'select', None
        self.columns, self.ordering, self.cap, self.single, self.negated = '*', None, None, False, False
    def select(self, columns='*', **kwargs): self.columns=columns; return self
    def eq(self, k, v): self.filters.append(lambda p,k=k,v=v:p.get(k)==v); return self
    def gte(self,k,v): self.filters.append(lambda p,k=k,v=v:p.get(k) is not None and p[k]>=v); return self
    def lt(self,k,v): self.filters.append(lambda p,k=k,v=v:p.get(k) is not None and p[k]<v); return self
    def in_(self,k,v): self.filters.append(lambda p,k=k,v=set(v):p.get(k) in v); return self
    @property
    def not_(self): self.negated=True; return self
    def is_(self,k,v):
        negate=self.negated; self.negated=False
        self.filters.append(lambda p,k=k,n=negate:(p.get(k) is not None) if n else (p.get(k) is None));return self
    def order(self,k,desc=False): self.ordering=(k,desc); return self
    def limit(self,n): self.cap=n; return self
    def maybe_single(self):self.single=True;return self
    def insert(self,values):self.mode='insert';self.values=values;return self
    def update(self,values):self.mode='update';self.values=values;return self
    def execute(self):
        records=self.db.tables.setdefault(self.table,[])
        if self.mode=='insert':
            added=deepcopy(self.values if isinstance(self.values,list) else [self.values])
            if self.table=='newsletter_posts':
                for p in added:
                    if any(p['newsletter_id']==r['newsletter_id'] and (p['position']==r['position'] or p['blog_post_id']==r['blog_post_id']) for r in records):raise RuntimeError('23505')
            records.extend(added);return Result(deepcopy(added))
        if self.mode=='update' and self.db.before_update:
            hook=self.db.before_update;self.db.before_update=None;hook(self.db,self.table)
        rows=[r for r in records if all(f(r) for f in self.filters)]
        if self.mode=='update':
            for r in rows:r.update(deepcopy(self.values))
        if self.ordering:
            k,desc=self.ordering;rows.sort(key=lambda r:(r.get(k) is None, r.get(k)),reverse=desc)
        if self.cap is not None:rows=rows[:self.cap]
        rows=deepcopy(rows)
        if self.columns!='*':rows=[{k.strip():r.get(k.strip()) for k in self.columns.split(',')} for r in rows]
        return Result((rows[0] if rows else None) if self.single else rows)

class DB:
    def __init__(self,tables):self.tables=deepcopy(tables);self.before_update=None
    def table(self,name):return Query(self,name)

def post(index,category='SHOPPERS'):
    return {'id':f'p{index}','title':f'Story {index}','category':category,'status':'published','blogger_url':f'https://news.youdle.io/{index}','image_url':f'https://i.ibb.co/image{index}.jpg','html_content':'<p>Published article body</p>','blogger_published_at':STAMP,'archived_at':None}

def edition(status='draft'):
    return {'id':'same-edition','title':'Existing issue','subject':'Existing compelling subject','status':status,'html_content':'old','created_at':STAMP,'updated_at':STAMP}

def fake_render(db,ids,subject,**kwargs):return subject+' '+','.join(ids)

class EditionTests(unittest.TestCase):
    def test_late_publications_join_same_issue_and_recall_stays_last(self):
        db=DB({'newsletters':[edition()],'blog_posts':[post(i) for i in range(6)]+[post(6,'RECALL')],'newsletter_posts':[{'id':str(i),'newsletter_id':'same-edition','blog_post_id':f'p{i}','position':i} for i in range(3)]})
        first=sync_weekly_draft(db,fake_render,now=NOW,require_complete=True)
        second=sync_weekly_draft(db,fake_render,now=NOW,require_complete=True)
        self.assertEqual(first['newsletter']['id'],'same-edition');self.assertEqual(second['newsletter']['id'],'same-edition')
        self.assertEqual(len(db.tables['newsletters']),1);self.assertEqual(len(db.tables['newsletter_posts']),7)
        self.assertGreaterEqual(next(p['position'] for p in db.tables['newsletter_posts'] if p['blog_post_id']=='p6'),RECALL_POSITION)
        self.assertIn('p0,p1,p2,p3,p4,p5,p6',db.tables['newsletters'][0]['html_content'])
    def test_scheduled_issue_is_not_changed_or_split(self):
        db=DB({'newsletters':[edition('scheduled')],'blog_posts':[post(8)],'newsletter_posts':[]});before=deepcopy(db.tables)
        result=sync_weekly_draft(db,fake_render,now=NOW)
        self.assertTrue(result['locked']);self.assertEqual(db.tables,before)
    def test_auto_creation_waits_for_full_issue_then_reuses_it(self):
        db=DB({'newsletters':[],'blog_posts':[post(i) for i in range(3)],'newsletter_posts':[]})
        self.assertIsNone(sync_weekly_draft(db,fake_render,now=NOW,require_complete=True))
        db.tables['blog_posts']=[post(i) for i in range(6)]+[post(6,'RECALL')]
        result=sync_weekly_draft(db,fake_render,now=NOW,require_complete=True)
        again=sync_weekly_draft(db,fake_render,now=NOW,require_complete=True)
        self.assertEqual(result['newsletter']['id'],again['newsletter']['id']);self.assertEqual(len(db.tables['newsletters']),1)
    def test_competing_html_update_reloads_memberships_without_loss(self):
        db=DB({'newsletters':[edition()],'blog_posts':[post(1),post(2)],'newsletter_posts':[{'id':'link1','newsletter_id':'same-edition','blog_post_id':'p1','position':0}]})
        def competing(db,table):
            if table=='newsletters':
                db.tables['newsletters'][0]['updated_at']='2026-11-12T04:00:01+00:00'
                db.tables['blog_posts'].append(post(3));db.tables['newsletter_posts'].append({'id':'link3','newsletter_id':'same-edition','blog_post_id':'p3','position':2})
        db.before_update=competing
        sync_weekly_draft(db,fake_render,now=NOW)
        self.assertIn('p1,p2,p3',db.tables['newsletters'][0]['html_content'])
    def test_photo_overrides_survive_another_refresh(self):
        image='https://i.ibb.co/approved.jpg';url='https://news.youdle.io/story'
        self.assertEqual(existing_images(f'<a href="{url}"><img src="{image}"></a>'),{url:image})

class DesignTests(unittest.TestCase):
    def test_approved_branding_photos_arrows_and_all_stories_are_retained(self):
        stories=[{'title':f'New article {i}','url':f'https://news.youdle.io/new{i}','image_url':f'https://i.ibb.co/new{i}.jpg','category':'SHOPPERS','summary':'Current verified summary.'} for i in range(13)]
        recall={'title':'Current recall','url':'https://news.youdle.io/recall','image_url':'https://i.ibb.co/recall.jpg','category':'RECALL'}
        body=render_youdle_newsletter_html(stories,[recall],'Preview of actual stories')
        self.assertEqual(body.count('Read article '),14);self.assertEqual(body.count('<img '),15)
        self.assertIn('Youdle Logo',body);self.assertIn("Georgia,",body);self.assertIn('#28543d',body)
        self.assertIn('Preview of actual stories',body);self.assertIn('*|UNSUB|*',body)
        self.assertGreater(body.index('https://news.youdle.io/recall'),body.index('https://news.youdle.io/new12'))
        for text in ('GrocerySOS','Grocery Brief','mailto:','__ARTICLE_', 'holiday-shopping-early'):
            self.assertNotIn(text,body)
    def test_subject_uses_real_headlines(self):
        subject=preview_subject([{'title':'Formula prices rise. What to check.'},{'title':'Delivery fees explained.'}])
        self.assertIn('Formula prices rise',subject);self.assertIn('Delivery fees explained',subject)
        self.assertNotIn('More Stories',subject);self.assertNotIn('Weekly -',subject)

class CampaignTests(unittest.TestCase):
    def test_existing_unsent_campaign_is_reused_and_verified(self):
        from api.routes.newsletters import _prepare_newsletter_campaign
        db=DB({'newsletters':[edition()]});mail=MagicMock()
        mail.client.campaigns.get.return_value={'status':'save','settings':{'subject_line':'Actual story preview'}}
        body='<a href="https://news.youdle.io/story"><img src="https://i.ibb.co/image.jpg"></a>'
        mail.client.campaigns.content.get.return_value={'html':body}
        n={'id':'same-edition','mailchimp_campaign_id':'same-campaign','subject':'Actual story preview','html_content':body}
        result=_prepare_newsletter_campaign(db,mail,n)
        self.assertEqual(result['campaign_id'],'same-campaign');mail.create_campaign.assert_not_called()
        mail.client.campaigns.content.update.assert_called_once_with('same-campaign',{'html':body})
    def test_already_sent_campaign_never_creates_a_second_one(self):
        from api.routes.newsletters import _prepare_newsletter_campaign
        from fastapi import HTTPException
        db=DB({'newsletters':[edition()]});mail=MagicMock();mail.client.campaigns.get.return_value={'status':'sent'}
        with self.assertRaises(HTTPException):_prepare_newsletter_campaign(db,mail,{'mailchimp_campaign_id':'same-campaign'})
        mail.create_campaign.assert_not_called()

if __name__=='__main__':unittest.main()
