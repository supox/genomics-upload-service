"""Simple template rendering utility"""

import os
import re
from pathlib import Path
from typing import Dict, Any


def render_template(template_name: str, **kwargs: Any) -> str:
    """
    Render a template with the given variables.
    
    Args:
        template_name: Name of the template file (without .html extension)
        **kwargs: Variables to substitute in the template
        
    Returns:
        Rendered HTML string
    """
    template_path = Path(__file__).parent.parent / "templates" / f"{template_name}.html"
    
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_name}.html")
    
    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()
    
    # Find all template variables using regex
    variable_pattern = r'\{\{([^}]+)\}\}'
    matches = re.findall(variable_pattern, template_content)
    
    for match in matches:
        variable_name = match.strip()
        
        try:
            # Handle complex expressions with dot notation
            if '.' in variable_name:
                value = _resolve_complex_variable(variable_name, kwargs)
            else:
                # Simple variable
                value = kwargs.get(variable_name, "")
            
            if value is None:
                value = ""
            
            # Replace the variable in the template
            template_content = template_content.replace(f'{{{{{variable_name}}}}}', str(value))
            
        except Exception as e:
            # If we can't resolve the variable, leave it as empty string
            template_content = template_content.replace(f'{{{{{variable_name}}}}}', "")
    
    return template_content


def _resolve_complex_variable(variable_name: str, context: Dict[str, Any]) -> Any:
    """
    Resolve complex variable expressions like 'upload_job.id' or 'upload_job.created_at.strftime("%Y-%m-%d %H:%M:%S")'
    """
    # Handle expressions with 'or' operator (e.g., 'upload_job.pattern or "None"')
    if ' or ' in variable_name:
        parts = variable_name.split(' or ', 1)
        try:
            main_value = _resolve_dot_notation(parts[0].strip(), context)
            if main_value:
                return main_value
            else:
                # Return the fallback value, removing quotes if present
                fallback = parts[1].strip()
                if fallback.startswith(("'", '"')) and fallback.endswith(("'", '"')):
                    return fallback[1:-1]
                return fallback
        except:
            # If main value fails, try fallback
            fallback = parts[1].strip()
            if fallback.startswith(("'", '"')) and fallback.endswith(("'", '"')):
                return fallback[1:-1]
            return fallback
    
    # Handle regular dot notation
    return _resolve_dot_notation(variable_name, context)


def _resolve_dot_notation(expression: str, context: Dict[str, Any]) -> Any:
    """
    Resolve dot notation like 'upload_job.id' or 'upload_job.created_at.strftime("%Y-%m-%d %H:%M:%S")'
    """
    # Handle method calls like strftime
    if '(' in expression and ')' in expression:
        # Extract method call
        method_match = re.match(r'([^(]+)\(([^)]*)\)', expression)
        if method_match:
            obj_path = method_match.group(1).strip()
            method_args = method_match.group(2).strip()
            
            # Get the object
            obj = _get_nested_attribute(obj_path, context)
            
            # Handle method call - for now, just handle strftime
            if obj_path.endswith('.strftime'):
                # Remove .strftime from the path to get the datetime object
                datetime_path = obj_path[:-9]  # Remove '.strftime'
                datetime_obj = _get_nested_attribute(datetime_path, context)
                
                # Extract format string from method args
                format_str = method_args.strip('\'"')
                if hasattr(datetime_obj, 'strftime'):
                    return datetime_obj.strftime(format_str)
            
            return obj
    
    # Handle simple dot notation
    return _get_nested_attribute(expression, context)


def _get_nested_attribute(path: str, context: Dict[str, Any]) -> Any:
    """
    Get nested attribute from context using dot notation like 'upload_job.id'
    """
    parts = path.split('.')
    obj = context
    
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            obj = getattr(obj, part, None)
        
        if obj is None:
            return None
    
    return obj


def render_error_template(title: str, message: str) -> str:
    """Render an error template with title and message"""
    return render_template("error", title=title, message=message)


def render_success_template(title: str, message: str, details: str = "", primary_action: Dict[str, str] = None) -> str:
    """Render a success template with title, message, and optional details"""
    if primary_action is None:
        primary_action = {"url": "/", "text": "Go Home"}
    
    return render_template("success", 
                         title=title, 
                         message=message, 
                         details=details,
                         primary_action=primary_action) 
