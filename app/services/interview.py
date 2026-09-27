def build_mock(job, profile):
    text=job.get('description','') or ''
    title=job.get('title','')
    skills=[x.strip() for x in profile.get('skills','').split(',') if x.strip()][:12]
    questions=[
      {'type':'opening','question':f'Tell me about yourself and why you are interested in the {title} role.','focus':'role alignment'},
      {'type':'experience','question':'Walk me through a project where you solved a difficult technical problem.','focus':'evidence'},
      {'type':'technical','question':f'How would you approach the core technical requirements described for {title}?','focus':', '.join(skills[:5])},
      {'type':'behavioral','question':'Tell me about a time you received difficult feedback and changed your approach.','focus':'learning'},
      {'type':'role-specific','question':'Which part of this job description would require the most ramp-up from you, and how would you handle it?','focus':'gap management'},
    ]
    return {'job':title,'company':job.get('company',''),'questions':questions,'technical_stack':skills,'source_text_length':len(text)}
