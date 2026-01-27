from __future__ import annotations
from typing import Optional, List, Dict, Any, Type
from pydantic import BaseModel, Field
import logging

try:
    import pubchempy as pcp
except Exception:
    pcp = None

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
        
        # [DEBUG] Log the tool invocation
        log.info(f"CompoundDatabaseTool called with: name='{compound_name}', mass={mass}, formula='{formula}', smiles='{smiles}'")

        if not pcp and not smiles:
            return json.dumps({"error": True, "message": "PubChemPy not installed and no SMILES provided. Install pubchempy or provide SMILES."})

        results: List[Dict[str, Any]] = []

        # --- Name search ---
        if compound_name and pcp:
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
            # keep 50 max (User requested "all")
            payload["synonyms"] = list(dict.fromkeys([s.strip() for s in syn_set]))[:50]
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

    def _search_by_name(self, compound_name: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not pcp:
            return out
        try:
            comps = pcp.get_compounds(compound_name, 'name', listkey_count=5)
            for c in comps[:5]:
                smiles_c = getattr(c, 'connectivity_smiles', None) or getattr(c, 'canonical_smiles', None)
                mass = None
                if smiles_c and RDKIT_AVAILABLE:
                    try:
                        mol = Chem.MolFromSmiles(smiles_c)
                        mass = round(Descriptors.MolWt(mol), 4) if mol else None
                    except Exception:
                        mass = None
                out.append({
                    'name': getattr(c, 'iupac_name', None) or (c.synonyms[0] if getattr(c, 'synonyms', None) else compound_name),
                    'formula': getattr(c, 'molecular_formula', None),
                    'mass': mass,
                    'smiles': smiles_c,
                    'cid': getattr(c, 'cid', None),
                    'synonyms': getattr(c, 'synonyms', None) or []
                })
        except Exception as e:
            log.warning(f"PubChem name search failed: {e}")
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
