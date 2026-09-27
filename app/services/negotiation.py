def model_offer(base_salary, market_low, market_high, experience_years=0):
    base=float(base_salary or 0); low=float(market_low or 0); high=float(market_high or 0)
    midpoint=(low+high)/2 if high else low
    target=max(base,midpoint)
    return {'current_offer':base,'market_low':low,'market_high':high,'reference_midpoint':round(midpoint,2),'counter_reference':round(target,2),'note':'Market figures must be supplied from a current, identified source; this model does not infer employer budget limits.'}

def counter_script(role, company, amount, flexibility='salary'):
    return f"Thank you for the offer for the {role} position at {company}. Based on the scope of the role and the market range I am using as a reference, I would like to discuss a total package around {amount:,.0f}. I am also open to discussing the broader {flexibility} package if there is flexibility there."
