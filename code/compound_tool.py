from __future__ import annotations
from typing import Optional, List, Dict, Any, Type
from contextvars import ContextVar
import re
from pydantic import BaseModel, Field
import logging
import warnings

try:
    import pubchempy as pcp
except Exception:
    pcp = None

try:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")
        import pyopsin
except Exception:
    pyopsin = None

try:
    from py2opsin import py2opsin as py2opsin_convert
except Exception:
    py2opsin_convert = None

try:
    from rdkit import Chem
    from rdkit.Chem import Descriptors
    RDKIT_AVAILABLE = True
except Exception:
    Chem = None
    Descriptors = None
    RDKIT_AVAILABLE = False

try:
    from langchain.tools import BaseTool
except Exception:
    # Minimal fallback if langchain is not installed
    class BaseTool:
        pass

log = logging.getLogger("compound_agent")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


_OPSIN_INSTANCE = None
_TARGET_COMPOUND_CVAR: ContextVar[Optional[str]] = ContextVar("TARGET_COMPOUND", default=None)


def _normalize_name_for_match(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _has_unbalanced_parentheses(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    return value.count("(") != value.count(")")


def _should_prefer_target_name(observed_name: str | None, target_name: str | None) -> bool:
    if not isinstance(observed_name, str) or not observed_name.strip():
        return True
    if not isinstance(target_name, str) or not target_name.strip():
        return False
    observed = observed_name.strip()
    target = target_name.strip()
    if observed == target:
        return False

    observed_norm = _normalize_name_for_match(observed)
    target_norm = _normalize_name_for_match(target)
    if not observed_norm or not target_norm:
        return False
    if observed_norm == target_norm:
        return False

    # Guard against truncated / malformed aliases such as unmatched-parenthesis variants.
    if _has_unbalanced_parentheses(observed):
        return True
    if len(observed_norm) >= 6 and observed_norm in target_norm:
        return True
    return False


def safe_tool_wrapper(func):
    """Wrapper to ensure tools return meaningful strings and catch exceptions."""
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            if result is None or (isinstance(result, str) and result.strip() == ""):
                return "No information available for this query."
            return result
        except Exception as e:
            cls_name = getattr(func, "__self__", None)
            if cls_name:
                cls_name = cls_name.__class__.__name__
            else:
                cls_name = func.__qualname__.split(".")[0]
            log.exception(f"Tool error in {cls_name}.{func.__name__}: {e}")
            return f"Tool '{cls_name}.{func.__name__}' error occurred: {str(e)}"
    return wrapper


class CompoundDatabaseInput(BaseModel):
    compound_name: Optional[str] = Field(None, description="Name of the compound")
    mass: Optional[float] = Field(None, description="Molecular mass")
    formula: Optional[str] = Field(None, description="Molecular formula")
    smiles: Optional[str] = Field(None, description="SMILES notation")
    return_format: str = Field("markdown", description="One of: markdown|json|both")


class CompoundDatabaseTool(BaseTool):
    name: str = "compound_database"
    description: str = "Look up compound information from PubChem and analyze SMILES with RDKit (when available)."
    args_schema: Type[BaseModel] = CompoundDatabaseInput

    @staticmethod
    def set_target_compound(name: Optional[str]) -> None:
        _TARGET_COMPOUND_CVAR.set(name.strip() if isinstance(name, str) else None)

    @safe_tool_wrapper
    def _run(self,
            compound_name: Optional[str] = None,
            mass: Optional[float] = None,
            formula: Optional[str] = None,
            smiles: Optional[str] = None) -> str:
        """
        Returns a JSON string only.
        Schema (examples):
        {
        "error": false,
        "primary": {
            "name": "Acetaminophen",
            "pubchem_cid": 1983,
            "smiles": "CC(=O)NC1=CC=C(O)C=C1",
            "formula": "C8H9NO2",
            "mass_da": 151.06333
        },
        "candidates": [
            {"name":"...", "pubchem_cid":123, "smiles":"...", "formula":"...", "mass_da":151.06333}
        ],
        "synonyms": ["Paracetamol", "APAP"],
        "smiles_analysis": {
            "input_smiles": "CC(=O)NC1=CC=C(O)C=C1",
            "formula": "C8H9NO2",
            "exact_mass_da": 151.06333
        },
        "notes": []
        }
        or on error:
        {"error": true, "message": "No compounds found."}
        """
        import json

        # --- Early validation / environment checks ---
        if not any([compound_name, mass, formula, smiles]):
            return json.dumps({"error": True, "message": "Please provide at least one of: compound_name, mass, formula, or smiles."})
        
        target_name = _TARGET_COMPOUND_CVAR.get()
        if _should_prefer_target_name(compound_name, target_name):
            log.info(
                "CompoundDatabaseTool overriding malformed/truncated input '%s' with target '%s'",
                compound_name,
                target_name,
            )
            compound_name = target_name

        # [DEBUG] Log the tool invocation
        log.info(f"CompoundDatabaseTool called with: name='{compound_name}', mass={mass}, formula='{formula}', smiles='{smiles}'")

        if not pcp and not smiles and not compound_name:
            return json.dumps({"error": True, "message": "PubChemPy not installed and no SMILES or compound_name provided. Install pubchempy or provide SMILES."})

        results: List[Dict[str, Any]] = []

        # --- Name search ---
        if compound_name:
            try:
                results.extend(self._search_by_name(compound_name))
            except Exception as e:
                log.warning(f"Name search failed: {e}")

        # --- Mass search ---
        if mass and pcp:
            try:
                compounds = pcp.get_compounds(str(mass), 'mass', listkey_count=5)
                for cmpd in compounds[:3]:
                    smiles_c = getattr(cmpd, 'connectivity_smiles', None) or getattr(cmpd, 'canonical_smiles', None)
                    mw = None
                    if smiles_c and RDKIT_AVAILABLE:
                        try:
                            mol = Chem.MolFromSmiles(smiles_c)
                            if mol:
                                # Prefer exact monoisotopic if available; fallback to average
                                try:
                                    mw = round(Chem.rdMolDescriptors.CalcExactMolWt(mol), 6)  # type: ignore[attr-defined]
                                except Exception:
                                    mw = round(Descriptors.MolWt(mol), 4)
                        except Exception:
                            mw = None
                    results.append({
                        'name': getattr(cmpd, 'iupac_name', None) or (cmpd.synonyms[0] if getattr(cmpd, 'synonyms', None) else None) or 'Unknown',
                        'formula': getattr(cmpd, 'molecular_formula', None),
                        'mass': mw or mass,
                        'smiles': smiles_c,
                        'cid': getattr(cmpd, 'cid', None),
                    })
            except Exception as e:
                log.warning(f"Mass search failed: {e}")

        # --- Formula search ---
        if formula and pcp:
            try:
                results.extend(self._search_by_formula(formula))
            except Exception as e:
                log.warning(f"Formula search failed: {e}")

        # --- SMILES search ---
        if smiles:
            try:
                results.extend(self._search_by_smiles(smiles))
            except Exception as e:
                log.warning(f"SMILES search failed: {e}")

        # --- Deduplicate by CID (if present) ---
        unique_results: List[Dict[str, Any]] = []
        seen_cids = set()
        for r in results:
            cid = r.get('cid')
            if cid and cid not in seen_cids:
                unique_results.append(r)
                seen_cids.add(cid)
            elif not cid:
                unique_results.append(r)

        # --- Build payload ---
        payload: Dict[str, Any] = {
            "error": False,
            "primary": {},
            "candidates": [],
            "synonyms": [],
            "smiles_analysis": {},
            "notes": []
        }

        # harvest synonyms if present (only _search_by_name populates them)
        try:
            syn_set = {s for r in results for s in (r.get('synonyms') or []) if isinstance(s, str) and s.strip()}
            payload["synonyms"] = list(dict.fromkeys([s.strip() for s in syn_set]))
        except Exception:
            payload["synonyms"] = []

        # If we have any candidates, choose the first as primary
        if unique_results:
            first_r = unique_results[0] or {}
            payload["primary"] = {
                "name": first_r.get("name") or "",
                "pubchem_cid": first_r.get("cid") or "",
                "smiles": first_r.get("smiles") or "",
                "formula": first_r.get("formula") or "",
                "mass_da": first_r.get("mass") or ""
            }
            # Candidates list (up to 10)
            payload["candidates"] = [
                {
                    "name": r.get("name") or "",
                    "pubchem_cid": r.get("cid") or "",
                    "smiles": r.get("smiles") or "",
                    "formula": r.get("formula") or "",
                    "mass_da": r.get("mass") or ""
                } for r in unique_results[:10]
            ]
        else:
            # No results at all
            if smiles and RDKIT_AVAILABLE:
                # Provide at least SMILES analysis as structured fields
                try:
                    mol = Chem.MolFromSmiles(smiles)
                    if mol:
                        try:
                            exact_mw = round(Chem.rdMolDescriptors.CalcExactMolWt(mol), 6)  # type: ignore[attr-defined]
                        except Exception:
                            exact_mw = round(Descriptors.MolWt(mol), 4)
                        formula_calc = Chem.rdMolDescriptors.CalcMolFormula(mol)  # type: ignore[attr-defined]
                        payload["smiles_analysis"] = {
                            "input_smiles": smiles,
                            "formula": formula_calc,
                            "exact_mass_da": exact_mw
                        }
                    else:
                        payload["notes"].append(f"Invalid SMILES: {smiles}")
                except Exception as e:
                    payload["notes"].append(f"SMILES analysis failed: {e}")
            # If still nothing meaningful, return a clean error
            if not payload["smiles_analysis"]:
                return json.dumps({"error": True, "message": "No compounds found. Try a different query."})

        if payload["synonyms"]:
             log.info(f"CompoundDatabaseTool found {len(payload['synonyms'])} synonyms for {payload.get('primary', {}).get('name', 'unknown')}")
        else:
             log.info("CompoundDatabaseTool found 0 synonyms.")

        return json.dumps(payload, ensure_ascii=False)

    def _search_by_smiles(self, smiles: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        # First try PubChem lookup by SMILES
        if pcp:
            try:
                comps = pcp.get_compounds(smiles, 'smiles', listkey_count=5)
                for c in comps[:3]:
                    out.append({
                        'name': getattr(c, 'iupac_name', None) or (c.synonyms[0] if getattr(c, 'synonyms', None) else None) or 'Unknown',
                        'formula': getattr(c, 'molecular_formula', None),
                        'mass': None,
                        'smiles': getattr(c, 'connectivity_smiles', None) or getattr(c, 'canonical_smiles', None) or smiles,
                        'cid': getattr(c, 'cid', None),
                    })
            except Exception as e:
                log.warning(f"PubChem SMILES lookup failed: {e}")
        # If RDKit available, compute mass
        if RDKIT_AVAILABLE:
            try:
                mol = Chem.MolFromSmiles(smiles)
                if mol:
                    mw = round(Descriptors.MolWt(mol), 4)
                    # attach mass to first result if present
                    if out:
                        out[0]['mass'] = mw
                    else:
                        out.append({'name': 'SMILES-only', 'formula': '', 'mass': mw, 'smiles': smiles, 'cid': None})
            except Exception as e:
                log.warning(f"RDKit analysis failed for SMILES: {e}")
        return out

    def _get_opsin_instance(self):
        global _OPSIN_INSTANCE
        if _OPSIN_INSTANCE is not None:
            return _OPSIN_INSTANCE
        if pyopsin is None:
            return None
        try:
            _OPSIN_INSTANCE = pyopsin.PyOpsin(exit_on_error=False)
            return _OPSIN_INSTANCE
        except Exception as e:
            log.warning(f"pyopsin initialization failed: {e}")
            return None

    def _resolve_name_to_smiles_with_opsin(self, compound_name: str) -> Optional[str]:
        opsin_instance = self._get_opsin_instance()
        if opsin_instance is not None:
            try:
                smiles = opsin_instance.to_smiles_single(compound_name)
                if smiles:
                    return str(smiles)
            except Exception as e:
                log.warning(f"pyopsin name resolution failed for '{compound_name}': {e}")

        if py2opsin_convert is not None:
            try:
                smiles = py2opsin_convert(compound_name)
                if smiles:
                    return str(smiles)
            except Exception as e:
                log.warning(f"py2opsin name resolution failed for '{compound_name}': {e}")

        return None

    def _build_opsin_candidate(self, compound_name: str, smiles_c: str) -> Dict[str, Any]:
        formula = None
        mass = None
        if RDKIT_AVAILABLE:
            try:
                mol = Chem.MolFromSmiles(smiles_c)
                if mol:
                    formula = Chem.rdMolDescriptors.CalcMolFormula(mol)  # type: ignore[attr-defined]
                    mass = round(Descriptors.MolWt(mol), 4)
            except Exception as e:
                log.warning(f"RDKit analysis failed for OPSIN-resolved SMILES '{smiles_c}': {e}")
        return {
            'name': compound_name,
            'formula': formula,
            'mass': mass,
            'smiles': smiles_c,
            'cid': None,
            'synonyms': [],
        }

    def _search_by_name(self, compound_name: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if pcp:
            try:
                comps = pcp.get_compounds(compound_name, 'name', listkey_count=5)
                for c in comps[:5]:
                    smiles_c = getattr(c, 'connectivity_smiles', None) or getattr(c, 'canonical_smiles', None)
                    resolved_name = getattr(c, 'iupac_name', None) or (c.synonyms[0] if getattr(c, 'synonyms', None) else compound_name)
                    if not smiles_c:
                        smiles_c = self._resolve_name_to_smiles_with_opsin(resolved_name) or self._resolve_name_to_smiles_with_opsin(compound_name)
                    mass = None
                    if smiles_c and RDKIT_AVAILABLE:
                        try:
                            mol = Chem.MolFromSmiles(smiles_c)
                            mass = round(Descriptors.MolWt(mol), 4) if mol else None
                        except Exception:
                            mass = None
                    out.append({
                        'name': resolved_name,
                        'formula': getattr(c, 'molecular_formula', None),
                        'mass': mass,
                        'smiles': smiles_c,
                        'cid': getattr(c, 'cid', None),
                        'synonyms': getattr(c, 'synonyms', None) or []
                    })
            except Exception as e:
                log.warning(f"PubChem name search failed: {e}")

        if not out:
            smiles_c = self._resolve_name_to_smiles_with_opsin(compound_name)
            if smiles_c:
                pubchem_from_smiles = self._search_by_smiles(smiles_c)
                if pubchem_from_smiles:
                    for result in pubchem_from_smiles:
                        if not result.get('name') or result.get('name') == 'SMILES-only':
                            result['name'] = compound_name
                    out.extend(pubchem_from_smiles)
                else:
                    out.append(self._build_opsin_candidate(compound_name, smiles_c))
        return out

    def _search_by_formula(self, formula: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not pcp:
            return out
        try:
            comps = pcp.get_compounds(formula, 'formula', listkey_count=5)
            for c in comps[:5]:
                out.append({
                    'name': getattr(c, 'iupac_name', None) or (c.synonyms[0] if getattr(c, 'synonyms', None) else 'Unknown'),
                    'formula': getattr(c, 'molecular_formula', None),
                    'mass': None,
                    'smiles': getattr(c, 'connectivity_smiles', None) or getattr(c, 'canonical_smiles', None),
                    'cid': getattr(c, 'cid', None),
                })
        except Exception as e:
            log.warning(f"PubChem formula search failed: {e}")
        return out

    def _analyze_smiles(self, smiles: str) -> str:
        if not RDKIT_AVAILABLE:
            return "RDKit not installed; cannot analyze SMILES. Install rdkit-pypi to enable analysis."
        try:
            mol = Chem.MolFromSmiles(smiles)
            if not mol:
                return f"Invalid SMILES: {smiles}"
            mw = round(Descriptors.MolWt(mol), 4)
            formula = Chem.rdMolDescriptors.CalcMolFormula(mol)
            return f"SMILES Analysis Results:\n- SMILES: {smiles}\n- Formula: {formula}\n- Molecular Weight: {mw} Da"
        except Exception as e:
            return f"Error analyzing SMILES: {e}"

    def _analyze_smiles_properties(self, smiles: str) -> str:
        return self._analyze_smiles(smiles)
