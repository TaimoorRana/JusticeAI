from nlp_service.services import ml_service, fact_service


def generate_report(conversation, ml_prediction, similar_precedents):
    report = {}
    ml_statistics = ml_service.get_statistics()
    conversation_facts = fact_service.get_resolved_fact_keys(conversation)

    # Prediction accuracy
    report['accuracy'] = 0

    # Data set size
    report['data_set'] = ml_statistics['data_set']['size']

    # Similar case count
    report['similar_case'] = len(similar_precedents)

    # Curves
    report['curves'] = {}

    possible_curve_outcomes = ml_statistics['regressor']
    for outcome in ml_prediction:
        if outcome in possible_curve_outcomes:
            report['curves'][outcome] = dict(possible_curve_outcomes[outcome])
            report['curves'][outcome]['outcome_value'] = ml_prediction[outcome]

    # Outcomes
    report['outcomes'] = {}

    for outcome in ml_prediction:
        if int(ml_prediction[outcome]) == 1:
            report['outcomes'][outcome] = True
        elif int(ml_prediction[outcome]) == 0:
            report['outcomes'][outcome] = False
        else:
            report['outcomes'][outcome] = ml_prediction[outcome]

    # Similar Precedents
    report['similar_precedents'] = []

    # Filter out all facts and outcomes that don't matter from precedents
    for precedent in similar_precedents:
        filtered_fact_dict = {k: v for k, v in precedent['facts'].items() if k in conversation_facts}
        precedent['facts'] = __dict_values_to_int(filtered_fact_dict)
        filtered_outcome_dict = {k: v for k, v in precedent['outcomes'].items() if k in ml_prediction}
        precedent['outcomes'] = __dict_values_to_int(filtered_outcome_dict)
        report['similar_precedents'].append(precedent)

    return report


def __dict_values_to_int(dict):
    for key in dict:
        if type(dict[key]) is str:
            try:
                dict[key] = int(float(dict[key]))
            except ValueError:
                pass
    return dict
