## Design Decisions

### Offline item co-occurrence                                                                                    
                                                                                                                                                                                             
 - Compute only from training interactions, with chronological/session boundaries preserved.                                                                                                 
 - Store top-k neighbours and weights as an immutable Parquet or array artifact keyed by item ID.                                                                                            
 - Record data hash, session definition, transform code, and unseen-item fallback.                                                                                                           
 - Test it against the reproduced baseline as a feature or initialization experiment.                                                                                                        
                                                                                                                                                                                             
 Risk: Co-occurrence built across validation, test, or future interactions leaks information. Also, co-occurrence “embeddings” and neighbour lookup are different outputs; define which one  
 the model consumes.

### Call cap and query-hash caching                                                                                                                                                
                                                                                                                                                                                             
 Cache against a canonical key such as:                                                                                                                                                      
                                                                                                                                                                                             
 ```text                                                                                                                                                                                     
provider + normalized_query + filters + cutoff_date + result_limit
 ```                                                                                                                                                                                         
                                                                                                                                                                                             
 Keep separate caps for API calls, retrieved documents, and LLM tokens. Similar-looking but semantically different queries must not accidentally share a cache result.     

### Top-25 local vector store                                                                                                                                                      
                                                                                                                                                                                             
 Do not make 25 papers the exclusive knowledge base. That would hard-code selection bias toward SASRec, MMoE, and PLE before diagnostics justify them.                                       
                                                                                                                                                                                             
 Use the 25 papers as:                                                                                                                                                                       
                                                                                                                                                                                             
 - A curated offline seed corpus.                                                                                                                                                            
 - A fallback during gateway outages.                                                                                                                                                        
 - A high-priority retrieval collection.                                                                                                                                                     
                                                                                                                                                                                             
 Allow bounded external search when the local corpus has no relevant evidence. Store licensed text or abstracts, not arbitrary scraped PDFs. Combine semantic retrieval with keyword/BM25    
 matching because exact terms such as NDCG@10, KuaiRand, and negative sampling matter.   
                                                                                                                                                            
                                                                                                                                                                                             
### Filter-only proxy                                                                                                                                                              
                                                                                                                                                                                             
 Proxy results may reject:                                                                                                                                                                   
                                                                                                                                                                                             
 - Crashes, OOMs, or NaN loss.                                                                                                                                                               
 - Failure to learn beyond a fixed proxy baseline.                                                                                                                                           
 - Extreme metric regression beyond a pre-registered threshold.                                                                                                                              
 - Runtime or memory that cannot fit the full budget.                                                                                                                                        
                                                                                                                                                                                             
 Proxy results must not promote a final architecture, update convergence, or be reported as official improvement.                                                                            
                                                                                                                                                                                             
 Use immutable, deterministic proxy manifests. Run the baseline on each proxy tier so rejection is relative to a valid local reference.                                                      
                                                                                                                                                                                             
### Multi-tier pruning:    (optional)                                                                                                                                                  
                                                                                                                                                                                             
 Use absolute gates, not “bottom performer” ranking:                                                                                                                                         
                                                                                                                                                                                             
 1. Static, schema, leakage, and evaluator checks.                                                                                                                                           
 2. Tiny mechanical smoke run.                                                                                                                                                               
 3. Medium proxy run for convergence and severe-regression checks.                                                                                                                           
 4. Full train and official validation.                                                                                                                                                      
                                                                                                                                                                                             
 If Tier 2 removes experiments merely because they rank below other proxy runs, it conflicts with the filter-only rule. Log all rejected proxy runs as proxy/non_comparable.    


### Transactional rollback                                                                                                                                                        
                                                                                                                                                                                             
 Do not literally roll back experiment history. Failed runs and their diffs must remain recorded.                                                                                            
                                                                                                                                                                                             
 Use:                                                                                                                                                                                        
                                                                                                                                                                                             
 - Isolated Git worktrees per experiment.                                                                                                                                                    
 - Immutable checkpoints and artifacts.                                                                                                                                                      
 - Atomic checkpoint writes with hashes.                                                                                                                                                     
 - stable_fallback as the parent of the next run.                                                                                                                                            
 - Removal of the failed branch from the active frontier—not deletion from history.                                                                                                          
                                                                                                                                                                                             
 OOM should first attempt an approved batch-size, accumulation, or precision recovery. Only abandon the branch after its recovery cap is exhausted.   

### Phase-boundary checks:         (optional)                                                                                                                                                 
                                                                                                                                                                                             
 Add typed contracts between stages:                                                                                                                                                         
                                                                                                                                                                                             
 - Schema and type compatibility.                                                                                                                                                            
 - Key uniqueness and required identifier coverage.                                                                                                                                          
 - Expected cardinality or permitted row-count change.                                                                                                                                       
 - Join expansion ratio.                                                                                                                                                                     
 - Split taint and temporal boundary checks.                                                                                                                                                 
 - Missingness and finite-value checks.                                                                                                                                                      
 - Artifact and code hashes.                                                                                                                                                                 
                                                                                                                                                                                             
 The distribution shift should usually raise a diagnostic, not fail the run. Fail only when a pre-declared safety boundary is violated.                                                                                                                                                               
### Local GitHub MCP adapter                                                                                                                                                       
                                                                                                                                                                                             
 Use the official GitHub Search API behind a small read-only MCP surface. Respect authentication and rate limits; GitHub currently documents 30 authenticated search requests/minute and     
 10/minute for code search: GitHub Search API (https://docs.github.com/en/rest/search/search).                                                                                               
                                                                                                               
 Repository retrieval must record license, commit SHA, file hash, and source URL. Retrieved code is untrusted until isolated and tested.                                                     

### Papers with Code MCP adapter                                                                                                                                  
                                                                                                                                                                                             
 The old Papers with Code API URL currently redirects to Hugging Face Trending Papers rather than serving the previous API: former API endpoint (https://paperswithcode.com/api/v1/docs/).   
 Do not make it a required provider.                                                                                                                                                         
                                                                                                                                                                                             
 Use OpenAlex or arXiv for paper discovery and GitHub for implementations. Keep the provider interface replaceable so Papers with Code can be added later if a stable API is confirmed.   
Using openalex most probably




