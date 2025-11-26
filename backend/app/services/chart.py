from typing import Dict, Any, List
import json

class ChartService:
    def generate_chart_option(self, chart_type: str, data: List[Dict[str, Any]], x_axis: str, y_axis: str) -> Dict[str, Any]:
        """
        Generates ECharts option dictionary.
        """
        
        # Bad Chart Interceptor Logic (Simplified)
        if chart_type == "pie" and self._is_time_series(data, x_axis):
            return {
                "error": True,
                "message": "检测到时间序列数据。饼图不适合展示此类数据。建议使用：折线图。",
                "recommendation": "line"
            }

        if chart_type == "bar":
            return self._generate_bar_chart(data, x_axis, y_axis)
        elif chart_type == "line":
            return self._generate_line_chart(data, x_axis, y_axis)
        elif chart_type == "pie":
            return self._generate_pie_chart(data, x_axis, y_axis)
        else:
            return {"error": True, "message": f"不支持的图表类型: {chart_type}"}

    def _is_time_series(self, data, x_axis):
        # Simple heuristic: check if x_axis values look like dates/times
        # For prototype, just return False or check specific column names
        if "date" in x_axis.lower() or "time" in x_axis.lower() or "month" in x_axis.lower() or "日期" in x_axis or "时间" in x_axis:
            return True
        return False

    def _generate_bar_chart(self, data, x_axis, y_axis):
        x_data = [str(item.get(x_axis, "")) for item in data]
        y_data = [item.get(y_axis, 0) for item in data]
        
        return {
            "title": {"text": f"{y_axis} 按 {x_axis} 分布"},
            "tooltip": {},
            "xAxis": {"data": x_data},
            "yAxis": {},
            "series": [{"name": y_axis, "type": "bar", "data": y_data}]
        }

    def _generate_line_chart(self, data, x_axis, y_axis):
        x_data = [str(item.get(x_axis, "")) for item in data]
        y_data = [item.get(y_axis, 0) for item in data]
        
        return {
            "title": {"text": f"{y_axis} 趋势图"},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": x_data},
            "yAxis": {"type": "value"},
            "series": [{"name": y_axis, "type": "line", "data": y_data}]
        }

    def _generate_pie_chart(self, data, x_axis, y_axis):
        pie_data = [{"name": str(item.get(x_axis, "")), "value": item.get(y_axis, 0)} for item in data]
        
        return {
            "title": {"text": f"{y_axis} 占比分布"},
            "tooltip": {"trigger": "item"},
            "series": [
                {
                    "name": y_axis,
                    "type": "pie",
                    "radius": "50%",
                    "data": pie_data,
                    "emphasis": {
                        "itemStyle": {
                            "shadowBlur": 10,
                            "shadowOffsetX": 0,
                            "shadowColor": "rgba(0, 0, 0, 0.5)"
                        }
                    }
                }
            ]
        }

chart_service = ChartService()
