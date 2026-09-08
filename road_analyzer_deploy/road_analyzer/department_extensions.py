def generate_recommendations(detections, reduced_capacity, base_capacity):
    recommendations = []
    if base_capacity <= 0:
        return recommendations

    capacity_loss_percent = (1 - (reduced_capacity / base_capacity)) * 100

    if capacity_loss_percent > 30:
        recommendations.append({
            "severity": "Critical",
            "action": "Recommended for engineering review: immediate traffic management and lane closure assessment.",
            "category": "capacity"
        })
    elif capacity_loss_percent > 20:
        recommendations.append({
            "severity": "High",
            "action": "Recommended for engineering review: implement temporary traffic calming and schedule urgent maintenance.",
            "category": "capacity"
        })
    elif capacity_loss_percent > 10:
        recommendations.append({
            "severity": "Medium",
            "action": "Recommended for engineering review: monitor and plan for routine maintenance within the next week.",
            "category": "capacity"
        })
    elif capacity_loss_percent > 3:
        recommendations.append({
            "severity": "Low",
            "action": "Recommended for engineering review: routine monitoring and minor repairs.",
            "category": "capacity"
        })

    for det in detections:
        cls = det["class"]
        if cls == "pothole":
            severity = det.get("severity", "unknown")
            if severity == "shallow":
                recommendations.append({
                    "severity": "Medium",
                    "action": "Recommended for engineering review: patch with hot‑mix/cold‑mix asphalt per IRC:SP:83‑2018.",
                    "category": "pothole"
                })
            elif severity == "moderate":
                recommendations.append({
                    "severity": "High",
                    "action": "Recommended for engineering review: repair using semi‑permanent patching within 7 days.",
                    "category": "pothole"
                })
            elif severity == "deep":
                recommendations.append({
                    "severity": "Critical",
                    "action": "Recommended for engineering review: immediate lane closure and full‑depth repair.",
                    "category": "pothole"
                })
        elif cls == "vendor":
            recommendations.append({
                "severity": "Medium",
                "action": "Recommended for engineering review: coordinate with TVC to relocate vendor as per Street Vendors Act, 2014.",
                "category": "vendor"
            })
        elif cls == "parked":
            recommendations.append({
                "severity": "High",
                "action": "Recommended for engineering review: enforce parking restrictions under MV Act, Sec.122.",
                "category": "parking"
            })
        elif cls == "cart":
            recommendations.append({
                "severity": "Low",
                "action": "Recommended for engineering review: remove hand‑cart from carriageway.",
                "category": "cart"
            })
        elif cls == "garbage":
            recommendations.append({
                "severity": "Medium",
                "action": "Recommended for engineering review: remove solid waste per Solid Waste Management Rules, 2016.",
                "category": "garbage"
            })
        elif cls == "barricade":
            recommendations.append({
                "severity": "Low",
                "action": "Recommended for engineering review: verify barricade placement and ensure proper signing.",
                "category": "barricade"
            })
        elif cls == "tree":
            recommendations.append({
                "severity": "Low",
                "action": "Recommended for engineering review: trim overhanging branches and ensure clear sight distance.",
                "category": "tree"
            })

    return recommendations
